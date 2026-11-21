"""Enriquecimento experimental das vagas INESC TEC.

Este módulo não altera vagas.json, situações, classificações ou publicação.
Os resultados são gravados num ficheiro separado e cada campo enriquecido
deve ter evidência textual e um URL de origem verificável.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

RAIZ = Path(__file__).parent
BASE_DADOS = RAIZ / "data" / "vagas.json"
SAIDA_DADOS = RAIZ / "data" / "enriquecimento.json"
OFICIAL_HOST = "www.inesctec.pt"
LIMITE_PADRAO = 5
USER_AGENT = "Mozilla/5.0 (compatible; oportunidades-hugo-enriquecimento/1.0)"

CAMPOS_ENRIQUECIDOS = (
    "descricao",
    "responsabilidades",
    "requisitos_obrigatorios",
    "requisitos_preferenciais",
    "competencias_tecnicas",
    "competencias_tecnicas_originais",
    "competencias_tecnicas_normalizadas",
    "idiomas",
    "localizacao",
    "modalidade",
    "jornada",
    "tipo_vinculo",
    "remuneracao",
    "moeda",
    "data_publicacao",
    "prazo_candidatura",
)

CABECALHOS_SECAO = (
    "NÍVEL REMUNERATÓRIO",
    "FUNÇÕES A DESEMPENHAR",
    "OBJETIVOS",
    "LOCAL DE TRABALHO",
    "ÁREA DE TRABALHO",
    "PERFIL REQUERIDO",
    "REQUISITOS MÍNIMOS",
    "FACTORES DE PREFERÊNCIA",
    "FATORES DE PREFERÊNCIA",
    "FORMALIZAÇÃO DAS CANDIDATURAS",
    "PROCESSO DE AVALIAÇÃO",
    "SEGUNDA FASE",
    "PERÍODO DE CANDIDATURA",
)


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip())


def ref_da_vaga(vaga: dict) -> str | None:
    link = vaga.get("link")
    if not isinstance(link, str):
        return None
    match = re.search(r"/editais/(pt|en)/([A-Za-z0-9-]+)$", link.rstrip("/"))
    return match.group(2) if match else None


def migrar_datas_historicas_inesctec(vagas: list[dict]) -> list[dict]:
    """Move o valor legado de candidaturaFim para prazo_candidatura.

    Esta correção é conservadora: não atribui uma data de publicação histórica
    nem altera IDs, URLs, situação ou primeira_observacao. As datas já existentes
    só são reinterpretadas no campo correto para registos INESC TEC sem evidência
    independente de publicação.
    """
    migradas = []
    for vaga in vagas:
        resultado = dict(vaga)
        if vaga.get("fonte") == "inesctec" and vaga.get("data_publicacao"):
            prazo = vaga.get("prazo_candidatura")
            if prazo is None:
                resultado["prazo_candidatura"] = vaga["data_publicacao"]
            resultado["data_publicacao"] = None
        migradas.append(resultado)
    return migradas


def url_oficial_valida(vaga: dict) -> str | None:
    link = vaga.get("link")
    if not isinstance(link, str) or vaga.get("fonte") != "inesctec":
        return None
    try:
        parsed = urllib.parse.urlsplit(link)
        if parsed.scheme != "https" or parsed.hostname != OFICIAL_HOST:
            return None
        match = re.fullmatch(r"/editais/(pt|en)/([A-Za-z0-9-]+)", parsed.path)
        if not match:
            return None
        return f"https://{OFICIAL_HOST}/editais/pt/{match.group(2)}"
    except (ValueError, TypeError):
        return None


def corresponder_vaga(vaga: dict, texto: str) -> bool:
    ref = ref_da_vaga(vaga)
    if not ref:
        return False
    normalizado = normalizar_texto(texto).lower()
    if ref.lower() not in normalizado:
        return False
    titulo = normalizar_texto(vaga.get("titulo", "")).lower()
    titulo_sem_ref = re.sub(r"\s*\(" + re.escape(ref.lower()) + r"\)\s*$", "", titulo).strip()
    return not titulo_sem_ref or titulo_sem_ref in normalizado


def validar_correspondencia_pdf(vaga: dict, texto: str, url: str) -> tuple[bool, str, str]:
    """Valida documento por referência, URL, título e instituição em hierarquia."""
    ref = ref_da_vaga(vaga)
    normalizado = normalizar_texto(texto).lower()
    refs_documento = set(re.findall(r"\bAE\d{4}-\d{4}\b", texto, re.I))
    if refs_documento:
        refs_normalizadas = {r.upper() for r in refs_documento}
        if len(refs_normalizadas) > 1:
            return False, "conflito_referencia", "O PDF contém referências de editais conflitantes"
        if not ref or ref.upper() not in refs_normalizadas:
            return False, "conflito_referencia", "O PDF contém outra referência de edital"
        return True, "referencia_explicita", "A referência explícita corresponde ao caminho da vaga"

    parsed = urllib.parse.urlsplit(url)
    ref_no_caminho = None
    match_caminho = re.search(r"/editais/(?:pt|en)/([A-Za-z0-9-]+)$", parsed.path)
    if match_caminho:
        ref_no_caminho = match_caminho.group(1)
    if not ref or ref_no_caminho != ref:
        return False, "referencia_incompativel", "A referência do caminho não corresponde à vaga"

    titulo = normalizar_texto(vaga.get("titulo", "")).lower()
    titulo_sem_ref = re.sub(r"\s*\(" + re.escape(ref.lower()) + r"\)\s*$", "", titulo).strip()
    titulo_corresponde = bool(titulo_sem_ref and titulo_sem_ref in normalizado)
    instituicao_corresponde = "inesc tec" in normalizado or "instituto de engenharia de sistemas" in normalizado
    area = normalizar_texto(vaga.get("categoria", "")).lower()
    area_corresponde = not area or area in normalizado

    if not titulo_corresponde:
        return False, "conflito_titulo", "Título normalizado não corresponde ao texto do PDF"
    if not instituicao_corresponde:
        return False, "conflito_instituicao", "Instituição não corresponde ao INESC TEC"
    if not area_corresponde:
        return False, "conflito_area", "Área de trabalho não corresponde ao registo"
    return True, "url_titulo_instituicao", "URL oficial, título, instituição e área são coerentes"


def _evidencia(
    url: str,
    campo: str,
    trecho: str,
    *,
    tipo_origem: str = "texto_verificado",
    verificado_em: str | None = None,
    status_http: int | None = None,
    content_type: str | None = None,
    titulo_ou_ref: str | None = None,
) -> dict:
    trecho_limpo = normalizar_texto(trecho)
    return {
        "campo": campo,
        "url": url,
        "tipo": tipo_origem,
        "verificado_em": verificado_em,
        "status_http": status_http,
        "content_type": content_type,
        "titulo_ou_ref": titulo_ou_ref,
        "trecho": trecho_limpo[:1000],
        "sha256_texto": sha256_texto(trecho_limpo),
    }


def _linhas(texto: str) -> list[str]:
    return [normalizar_texto(linha) for linha in texto.splitlines() if normalizar_texto(linha)]


def _extrair_secao(texto: str, rotulos: tuple[str, ...]) -> str | None:
    texto_normalizado = normalizar_texto(texto)
    fim_secao = re.compile(
        r"(?:Requisitos mínimos|Requisitos obrigatórios|Fatores de preferência|Área de trabalho|"
        r"Área científica|Responsabilidades|Atividades|Objetivos|Jornada|Modalidade|Remuneração|"
        r"Data de publicação|Prazo|Candidatura até|Bolsa|Contrato)",
        re.I,
    )
    for rotulo in rotulos:
        match = re.search(rotulo, texto_normalizado, re.I)
        if not match:
            continue
        inicio = match.end()
        resto = texto_normalizado[inicio:]
        resto = re.sub(r"^\s*[:\-]\s*", "", resto)
        proximo = fim_secao.search(resto)
        if proximo:
            resto = resto[:proximo.start()]
        valor = normalizar_texto(resto)
        if valor:
            return valor[:3000]
    return None


def _extrair_itens(texto: str, rotulos: tuple[str, ...]) -> list[str]:
    secao = _extrair_secao(texto, rotulos)
    if not secao:
        return []
    partes = re.split(r"\s*[•;]\s*|\n", secao)
    itens = []
    for parte in partes:
        limpa = re.sub(r"^(?:Requisitos mínimos|Fatores de preferência|[-•]\s*)", "", parte, flags=re.I)
        limpa = normalizar_texto(limpa)
        if limpa and limpa not in itens:
            itens.append(limpa)
    return itens[:20]


def _primeiro_data(texto: str, rotulos: tuple[str, ...]) -> str | None:
    texto_normalizado = normalizar_texto(texto)
    for match in re.finditer("|".join(rotulos), texto_normalizado, re.I):
        inicio = match.start()
        contexto = texto_normalizado[inicio:min(len(texto_normalizado), inicio + 160)]
        data_match = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", contexto)
        if data_match:
            return data_match.group(1)
    return None


def _extrair_prazo_candidatura(texto: str) -> tuple[str | None, str | None]:
    texto_normalizado = normalizar_texto(texto)
    match = re.search(r"PERÍODO DE CANDIDATURA.{0,300}", texto_normalizado, re.I)
    if not match:
        return None, None
    contexto = match.group(0)
    datas = re.findall(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", contexto)
    if not datas:
        return None, contexto
    return datas[-1], contexto


def _trecho_ao_redor(texto: str, rotulos: tuple[str, ...], tamanho: int = 900) -> str | None:
    texto_normalizado = normalizar_texto(texto)
    for rotulo in rotulos:
        match = re.search(rotulo, texto_normalizado, re.I)
        if match:
            inicio = max(0, match.start())
            fim = min(len(texto_normalizado), match.end() + tamanho)
            return texto_normalizado[inicio:fim]
    return None


def extrair_secao_delimitada(texto: str, inicio: str, fim: tuple[str, ...]) -> str | None:
    """Extrai uma seção até ao próximo cabeçalho conhecido, sem cortar listas."""
    texto_normalizado = normalizar_texto(texto)
    match_inicio = re.search(inicio, texto_normalizado, re.I)
    if not match_inicio:
        return None
    restante = texto_normalizado[match_inicio.end():]
    fim_match = None
    for rotulo in fim:
        match_fim = re.search(r"(?:^|[.!?]\s+|\s)" + re.escape(rotulo), restante, re.I)
        if match_fim and (fim_match is None or match_fim.start() < fim_match.start()):
            fim_match = match_fim
    secao = restante[:fim_match.start()] if fim_match else restante
    secao = re.sub(r"^[\s:•\-]+", "", normalizar_texto(secao))
    return secao or None


def _extrair_jornada(texto: str) -> str | None:
    normalizado = texto.lower()
    if re.search(r"\bjornada\s*[:\-]?\s*(?:de\s+)?tempo integral\b|\bfull[- ]?time\b", normalizado):
        return "Full Time"
    if re.search(r"\bjornada\s*[:\-]?\s*(?:de\s+)?tempo parcial\b|\bpart[- ]?time\b", normalizado):
        return "Part Time"
    return None


def _extrair_vinculo(texto: str) -> str | None:
    normalizado = texto.lower()
    padroes = (
        ("contrato sem termo", r"contrato (?:de trabalho )?(?:por tempo )?indeterminado|contrato sem termo"),
        ("contrato a termo certo", r"contrato a termo certo|contrato por tempo determinado"),
        ("contrato a termo incerto", r"contrato a termo incerto"),
        ("bolsa", r"\bbolsa(?:s)? de (?:investiga[cç][aã]o|inicia[cç][aã]o)\b|\bb[Ii]s?sa\b"),
    )
    for nome, padrao in padroes:
        if re.search(padrao, normalizado):
            return nome
    return None


def _extrair_modalidade(texto: str) -> str | None:
    normalizado = texto.lower()
    if re.search(r"\bremoto\b|\bteletrabalho\b", normalizado):
        return "remoto"
    if re.search(r"\bh[ií]brido\b", normalizado):
        return "hibrido"
    if re.search(r"\bpresencial\b", normalizado):
        return "presencial"
    return None


def _extrair_remuneracao(texto: str) -> tuple[str | None, str | None]:
    for linha in _linhas(texto):
        match = re.search(r"(€|\beur(?:os)?\b)\s*([0-9][0-9., ]*)|([0-9][0-9., ]*)\s*(€)", linha, re.I)
        if match:
            return normalizar_texto(linha), "EUR"
    return None, None


def extrair_texto_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return normalizar_texto(soup.get_text(" "))


def extrair_pdf_local(vaga: dict, url: str, caminho: Path, *, extraido_em: str | None = None) -> dict:
    """Extrai um PDF digital local e exige correspondência com a referência."""
    verificacao = extraido_em or agora_iso()
    caminho = Path(caminho)
    resultado = {
        "estado": "falha_pdf",
        "qualidade": "insuficiente",
        "descricao": None,
        "responsabilidades": [],
        "requisitos_obrigatorios": [],
        "requisitos_preferenciais": [],
        "competencias_tecnicas": [],
        "competencias_tecnicas_originais": [],
        "competencias_tecnicas_normalizadas": [],
        "idiomas": [],
        "localizacao": vaga.get("cidade"),
        "modalidade": None,
        "jornada": None,
        "tipo_vinculo": None,
        "remuneracao": None,
        "moeda": None,
        "data_publicacao": None,
        "prazo_candidatura": None,
        "evidencias": {},
        "fonte_oficial": url,
        "tipo_origem": "pdf",
        "documento_local": str(caminho),
        "data_extracao": verificacao,
    }
    if not caminho.is_file():
        resultado["estado"] = "pdf_inexistente"
        resultado["motivo"] = "Arquivo PDF não encontrado"
        return resultado

    bruto = caminho.read_bytes()
    resultado["sha256_documento"] = hashlib.sha256(bruto).hexdigest()
    resultado["tamanho_bytes"] = len(bruto)
    if not bruto.startswith(b"%PDF"):
        resultado["estado"] = "pdf_invalido"
        resultado["motivo"] = "O arquivo não possui assinatura PDF válida"
        return resultado

    try:
        leitor = PdfReader(__import__("io").BytesIO(bruto))
        paginas = []
        texto_por_pagina = []
        for numero, pagina in enumerate(leitor.pages, start=1):
            try:
                texto = pagina.extract_text() or ""
            except Exception:
                texto = ""
            texto_limpo = normalizar_texto(texto)
            paginas.append({"pagina": numero, "texto": texto_limpo})
            if texto_limpo:
                texto_por_pagina.append(texto_limpo)
    except (PdfReadError, ValueError, EOFError) as erro:
        resultado["estado"] = "pdf_invalido"
        resultado["motivo"] = f"PDF inválido: {type(erro).__name__}"
        return resultado

    texto_completo = normalizar_texto(" ".join(texto_por_pagina))
    if not texto_por_pagina:
        resultado["estado"] = "ocr_necessario"
        resultado["motivo"] = "PDF não contém texto digital extraível"
        resultado["paginas"] = paginas
        return resultado

    ref = ref_da_vaga(vaga)
    corresponde, criterio, motivo_correspondencia = validar_correspondencia_pdf(vaga, texto_completo, url)
    resultado["correspondencia"] = {
        "estado": "confirmada" if corresponde else "rejeitada",
        "criterio": criterio,
        "motivo": motivo_correspondencia,
    }
    if not corresponde:
        resultado["estado"] = "conteudo_nao_corresponde"
        resultado["motivo"] = motivo_correspondencia
        resultado["paginas"] = paginas
        return resultado

    evidencias_por_campo = {}

    def adicionar_evidencia(campo: str, valor: str | list[str], trecho: str, pagina: int) -> None:
        if isinstance(valor, list):
            texto_evidencia = " ".join(valor)
        else:
            texto_evidencia = str(valor)
        evidencias_por_campo.setdefault(campo, []).append({
            "campo": campo,
            "url": url,
            "tipo": "pdf",
            "pagina": pagina,
            "titulo_ou_ref": ref,
            "trecho": normalizar_texto(trecho)[:1000],
            "sha256_documento": resultado["sha256_documento"],
            "sha256_texto": sha256_texto(normalizar_texto(trecho)),
            "verificado_em": verificacao,
        })

    descricao = None
    for pagina in paginas:
        trecho = _trecho_ao_redor(
            pagina["texto"],
            (r"ÁREA DE TRABALHO:", r"Área de trabalho:", r"Área científica"),
            tamanho=1600,
        )
        if trecho:
            descricao = normalizar_texto(trecho)
            adicionar_evidencia("descricao", descricao, trecho, pagina["pagina"])
            break

    for pagina in paginas:
        secoes = [
            extrair_secao_delimitada(
                pagina["texto"],
                r"FUNÇÕES A DESEMPENHAR",
                ("OBJETIVOS", "LOCAL DE TRABALHO", "ÁREA DE TRABALHO"),
            ),
            extrair_secao_delimitada(
                pagina["texto"],
                r"Objetivos do plano de trabalho",
                ("LOCAL DE TRABALHO", "ÁREA DE TRABALHO", "PERFIL REQUERIDO"),
            ),
        ]
        responsabilidades = [s for s in secoes if s]
        if responsabilidades:
            resultado["responsabilidades"] = responsabilidades
            adicionar_evidencia("responsabilidades", responsabilidades, responsabilidades[0], pagina["pagina"])
            break

    for pagina in paginas:
        trecho = _trecho_ao_redor(pagina["texto"], (r"Requisitos mínimos:", r"PERFIL REQUERIDO"), tamanho=1300)
        if trecho:
            inicio = trecho.lower().find("requisitos mínimos:")
            fim = trecho.lower().find("factores de preferência:")
            bloco = trecho[inicio:fim] if inicio >= 0 and fim > inicio else trecho
            itens = [
                normalizar_texto(item)
                for item in re.split(r"\.\s+(?=[A-Z])", bloco)
                if normalizar_texto(item)
            ]
            resultado["requisitos_obrigatorios"] = itens
            adicionar_evidencia("requisitos_obrigatorios", itens, bloco, pagina["pagina"])
            break

    for pagina in paginas:
        trecho = _trecho_ao_redor(pagina["texto"], (r"Factores de preferência:", r"Fatores de preferência:"), tamanho=1300)
        if trecho:
            inicio = trecho.lower().find("factores")
            fim = trecho.lower().find("formalização das candidaturas")
            bloco = trecho[inicio:fim] if inicio >= 0 and fim > inicio else trecho
            itens = [
                normalizar_texto(item)
                for item in re.split(r"\.\s+(?=[A-Z])", bloco)
                if normalizar_texto(item)
            ]
            resultado["requisitos_preferenciais"] = itens
            adicionar_evidencia("requisitos_preferenciais", itens, bloco, pagina["pagina"])
            break

    for pagina in paginas:
        trecho = _trecho_ao_redor(
            pagina["texto"],
            (r"inteligência artificial", r"otimização matemática", r"gémeos digitais", r"sistemas elétricos"),
            tamanho=1100,
        )
        if trecho:
            originais = []
            for expressao in (
                "inteligência artificial",
                "otimização matemática",
                "decisão sob incerteza",
                "gémeos digitais",
                "modelização",
                "simulação",
                "previsão probabilística",
                "integração de conhecimento físico",
                "aprendizagem a partir de dados",
            ):
                if expressao in trecho.lower():
                    originais.append(expressao)
            resultado["competencias_tecnicas"] = [
                "Inteligência artificial",
                "Otimização matemática",
                "Gémeos digitais",
                "Modelização e simulação de sistemas elétricos",
            ]
            resultado["competencias_tecnicas_originais"] = originais
            resultado["competencias_tecnicas_normalizadas"] = [
                {"original": expressao, "categoria": {
                    "inteligência artificial": "Inteligência artificial",
                    "otimização matemática": "Otimização matemática",
                    "decisão sob incerteza": "Otimização sob incerteza",
                    "gémeos digitais": "Modelização digital",
                    "aprendizagem a partir de dados": "Aprendizagem de máquina aplicada",
                }.get(expressao, expressao)}
                for expressao in originais
            ]
            adicionar_evidencia("competencias_tecnicas", resultado["competencias_tecnicas"], trecho, pagina["pagina"])
            break

    for pagina in paginas:
        trecho = _trecho_ao_redor(pagina["texto"], (r"LOCAL DE TRABALHO",), tamanho=500)
        if trecho:
            resultado["localizacao"] = "INESC TEC, Porto, Portugal"
            adicionar_evidencia("localizacao", resultado["localizacao"], trecho, pagina["pagina"])
            break

    for pagina in paginas:
        trecho = pagina["texto"]
        if resultado["tipo_vinculo"] is None:
            vinculo = _extrair_vinculo(trecho)
            if vinculo:
                resultado["tipo_vinculo"] = vinculo
                adicionar_evidencia("tipo_vinculo", vinculo, trecho, pagina["pagina"])
        if resultado["prazo_candidatura"] is None:
            prazo, contexto_prazo = _extrair_prazo_candidatura(trecho)
            if prazo:
                resultado["prazo_candidatura"] = prazo
                adicionar_evidencia("prazo_candidatura", prazo, contexto_prazo or trecho, pagina["pagina"])

        if resultado["remuneracao"] is None:
            match_remuneracao = re.search(
                r"valor de\s+(€\s*[0-9][0-9.,]*)[^.]*",
                trecho,
                re.I,
            )
            if match_remuneracao:
                resultado["remuneracao"] = match_remuneracao.group(0).strip()
                resultado["moeda"] = "EUR"
                adicionar_evidencia("remuneracao", resultado["remuneracao"], match_remuneracao.group(0), pagina["pagina"])

    resultado["descricao"] = descricao
    resultado["evidencias"] = evidencias_por_campo
    resultado["paginas"] = paginas
    resultado["estado"] = "extraido"
    campos_confirmados = sum(bool(resultado.get(campo)) for campo in (
        "descricao",
        "responsabilidades",
        "requisitos_obrigatorios",
        "requisitos_preferenciais",
        "competencias_tecnicas",
        "localizacao",
        "tipo_vinculo",
    ))
    if campos_confirmados >= 6:
        resultado["qualidade"] = "concluida_validada"
        resultado["validacao_semantica"] = "confirmada"
        resultado["validacao_semantica_por_campo"] = {
            campo: bool(resultado.get(campo) and evidencias_por_campo.get(campo))
            for campo in ("descricao", "responsabilidades", "requisitos_obrigatorios",
                          "requisitos_preferenciais", "competencias_tecnicas",
                          "localizacao", "tipo_vinculo", "remuneracao", "prazo_candidatura")
        }
    elif campos_confirmados >= 3:
        resultado["qualidade"] = "parcial"
        resultado["validacao_semantica"] = "parcial"
    else:
        resultado["qualidade"] = "insuficiente"
        resultado["validacao_semantica"] = "insuficiente"
    return resultado


def extrair_payload(vaga: dict, url: str, conteudo: str, tipo: str = "html") -> dict:
    texto = normalizar_texto(conteudo if tipo == "texto" else extrair_texto_html(conteudo))
    correspondencia = corresponder_vaga(vaga, texto)
    resultado = {
        "descricao": None,
        "responsabilidades": [],
        "requisitos_obrigatorios": [],
        "requisitos_preferenciais": [],
        "competencias_tecnicas": [],
        "competencias_tecnicas_originais": [],
        "competencias_tecnicas_normalizadas": [],
        "idiomas": [],
        "localizacao": vaga.get("cidade"),
        "modalidade": None,
        "jornada": None,
        "tipo_vinculo": None,
        "remuneracao": None,
        "moeda": None,
        "data_publicacao": None,
        "prazo_candidatura": None,
        "evidencias": {},
        "fonte_oficial": url,
        "tipo_origem": tipo,
        "recolhido_em": None,
        "status_http": None,
        "content_type": None,
    }
    if not correspondencia:
        resultado["estado"] = "conteudo_nao_corresponde"
        resultado["qualidade"] = "insuficiente"
        return resultado

    descricao = _extrair_secao(texto, (r"Área de trabalho", r"Área científica", r"Descrição"))
    resultados = (
        ("descricao", descricao),
        ("responsabilidades", _extrair_itens(texto, (r"Responsabilidades", r"Atividades", r"Objetivos"))),
        ("requisitos_obrigatorios", _extrair_itens(texto, (r"Requisitos mínimos", r"Requisitos obrigatórios"))),
        ("requisitos_preferenciais", _extrair_itens(texto, (r"Fatores de preferência", r"Preferencial"))),
        ("competencias_tecnicas", _extrair_itens(texto, (r"Competências técnicas", r"Conhecimentos", r"Python", r"Pyomo"))),
        ("jornada", _extrair_jornada(texto)),
        ("tipo_vinculo", _extrair_vinculo(texto)),
        ("modalidade", _extrair_modalidade(texto)),
        ("data_publicacao", _primeiro_data(texto, (r"data de publicação", r"publicado em", r"data public"))),
        ("prazo_candidatura", _primeiro_data(texto, (r"prazo", r"candidatura até", r"termino", r"fim"))),
    )
    for campo, valor in resultados:
        if valor:
            resultado[campo] = valor
            resultado.setdefault("evidencias", {})[campo] = [
                _evidencia(
                    url,
                    campo,
                    str(valor),
                    tipo_origem=f"{tipo}_verificado",
                    verificado_em=agora_iso(),
                    titulo_ou_ref=ref_da_vaga(vaga),
                )
            ]

    remuneracao, moeda = _extrair_remuneracao(texto)
    if remuneracao:
        resultado["remuneracao"] = remuneracao
        resultado["moeda"] = moeda
        resultado["evidencias"]["remuneracao"] = [
            _evidencia(
                url,
                "remuneracao",
                remuneracao,
                tipo_origem=f"{tipo}_verificado",
                verificado_em=agora_iso(),
                titulo_ou_ref=ref_da_vaga(vaga),
            )
        ]

    idiomas = _extrair_itens(texto, (r"língua", r"línguas", r"idioma", r"English"))
    if idiomas:
        resultado["idiomas"] = idiomas
        resultado["evidencias"]["idiomas"] = [
            _evidencia(
                url,
                "idiomas",
                " ".join(idiomas),
                tipo_origem=f"{tipo}_verificado",
                verificado_em=agora_iso(),
                titulo_ou_ref=ref_da_vaga(vaga),
            )
        ]

    campos_positivos = sum(bool(resultado[c]) for c in CAMPOS_ENRIQUECIDOS)
    if descricao and (resultado["requisitos_obrigatorios"] or resultado["requisitos_preferenciais"]):
        qualidade = "fundamentada"
        estado = "extraido"
    elif campos_positivos >= 2:
        qualidade = "preliminar"
        estado = "incompleto"
    else:
        qualidade = "insuficiente"
        estado = "sem_dados_estruturados"
    resultado["estado"] = estado
    resultado["qualidade"] = qualidade
    return resultado


def buscar_html(url: str, timeout: int = 30) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resposta:
        status = resposta.status
        final_url = resposta.geturl()
        content_type = resposta.headers.get_content_type()
        bruto = resposta.read()
    if status >= 400:
        raise urllib.error.HTTPError(final_url, status, "HTTP error", {}, None)
    if content_type == "application/pdf" or bruto.startswith(b"%PDF"):
        return final_url, "__PDF_INCOMPLETO_SEM_EXTRATOR_VERIFICADO__"
    return final_url, bruto.decode("utf-8", errors="replace")


def resultado_falha(url: str, motivo: str, erro: str, agora: str) -> dict:
    return {
        "estado": "falha_acesso",
        "qualidade": "insuficiente",
        "motivo": motivo,
        "erro": erro,
        "fonte_oficial": url,
        "ultima_tentativa": agora,
        "evidencias": {},
    }


def preparar_falha(url: str, erro: Exception, agora: str) -> dict:
    if isinstance(erro, urllib.error.HTTPError):
        motivo = f"HTTP {erro.code}"
    elif isinstance(erro, (urllib.error.URLError, socket.gaierror, TimeoutError)):
        motivo = "DNS, timeout ou erro de rede"
    else:
        motivo = type(erro).__name__
    return resultado_falha(url, motivo, str(erro), agora)


def mesclar_resultado(anterior: dict | None, novo: dict, agora: str) -> dict:
    """Preserva campos enriquecidos anteriores em falhas sem apagar dados."""
    base = dict(anterior or {})
    if novo["estado"] == "falha_acesso":
        base.update({
            "estado": "falha_acesso",
            "qualidade": anterior.get("qualidade", "insuficiente") if anterior else "insuficiente",
            "motivo": novo["motivo"],
            "erro": novo["erro"],
            "ultima_tentativa": agora,
            "fonte_oficial": novo["fonte_oficial"],
        })
        return base
    base.pop("motivo", None)
    base.pop("erro", None)
    for campo in CAMPOS_ENRIQUECIDOS:
        valor = novo.get(campo)
        if valor not in (None, "", [], {}):
            base[campo] = valor
    base["estado"] = novo["estado"]
    base["qualidade"] = novo["qualidade"]
    base["fonte_oficial"] = novo.get("fonte_oficial", base.get("fonte_oficial"))
    base["tipo_origem"] = novo.get("tipo_origem", base.get("tipo_origem"))
    base["ultima_verificacao"] = agora
    evidencias_anteriores = dict(base.get("evidencias", {}) or {})
    evidencias_novas = dict(novo.get("evidencias", {}) or {})
    evidencias_anteriores.update(evidencias_novas)
    base["evidencias"] = evidencias_anteriores
    return base


def estrutura_inicial() -> dict:
    return {
        "schema": 1,
        "fonte": "inesctec",
        "atualizado_em": None,
        "vagas": {},
    }


def executar(
    *,
    base: Path = BASE_DADOS,
    saida: Path = SAIDA_DADOS,
    limite: int = LIMITE_PADRAO,
    agora: str | None = None,
    buscar=buscar_html,
) -> dict:
    timestamp = agora or agora_iso()
    dados_base = json.loads(base.read_text(encoding="utf-8"))
    vagas = dados_base.get("vagas", [])
    if saida.exists():
        anterior = json.loads(saida.read_text(encoding="utf-8"))
    else:
        anterior = estrutura_inicial()
    anterior_vagas = anterior.get("vagas", {})
    resultado = estrutura_inicial()
    resultado["atualizado_em"] = timestamp
    processadas = 0
    enriquecidas = 0

    for vaga in vagas:
        if vaga.get("fonte") != "inesctec":
            continue
        url = url_oficial_valida(vaga)
        if not url:
            continue
        if processadas >= limite:
            break
        processadas += 1
        anterior_item = anterior_vagas.get(url)
        try:
            final_url, conteudo = buscar(url)
            payload = extrair_payload(vaga, final_url, conteudo)
        except Exception as erro:
            payload = preparar_falha(url, erro, timestamp)
        item = mesclar_resultado(anterior_item, payload, timestamp)
        item["id_vaga"] = ref_da_vaga(vaga)
        item["titulo"] = vaga.get("titulo")
        item["situacao_vaga"] = vaga.get("situacao", "observada")
        item["ultima_verificacao"] = timestamp if payload["estado"] != "falha_acesso" else item.get("ultima_verificacao")
        resultado["vagas"][url] = item
        if item.get("estado") in ("extraido", "incompleto", "sem_dados_estruturados"):
            enriquecidas += 1

    resultado["total_processadas"] = processadas
    resultado["total_enriquecidas"] = enriquecidas
    resultado["total_registros_preservados"] = dados_base.get("total", len(vagas))
    return resultado


def gravar(resultado: dict, saida: Path = SAIDA_DADOS) -> None:
    saida.parent.mkdir(parents=True, exist_ok=True)
    temporario = saida.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(resultado, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporario.replace(saida)


def main() -> int:
    limite = LIMITE_PADRAO
    caminho_pdf = None
    ref_pdf = None
    if "--pdf" in sys.argv:
        indice = sys.argv.index("--pdf")
        try:
            caminho_pdf = sys.argv[indice + 1]
        except IndexError:
            caminho_pdf = None
    if "--edital" in sys.argv:
        indice = sys.argv.index("--edital")
        try:
            ref_pdf = sys.argv[indice + 1]
        except IndexError:
            ref_pdf = None
    if caminho_pdf:
        dados = json.loads(BASE_DADOS.read_text(encoding="utf-8"))
        vaga_pdf = next(
            (v for v in dados["vagas"]
             if v.get("fonte") == "inesctec"
             and ref_da_vaga(v) == ref_pdf),
            None,
        )
        if vaga_pdf is None:
            print(json.dumps({"erro": "Referência não encontrada em data/vagas.json"}, ensure_ascii=False))
            return 2
        url = url_oficial_valida(vaga_pdf)
        if not url:
            print(json.dumps({"erro": "URL oficial não é válida"}, ensure_ascii=False))
            return 2
        resultado = extrair_pdf_local(vaga_pdf, url, Path(caminho_pdf))
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    if "--limite" in sys.argv:
        indice = sys.argv.index("--limite")
        try:
            limite = max(0, min(5, int(sys.argv[indice + 1])))
        except (IndexError, ValueError):
            limite = LIMITE_PADRAO
    resultado = executar(limite=limite)
    gravar(resultado)
    print(json.dumps({
        "total_processadas": resultado["total_processadas"],
        "total_enriquecidas": resultado["total_enriquecidas"],
        "total_registros_preservados": resultado["total_registros_preservados"],
        "saida": str(SAIDA_DADOS),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
