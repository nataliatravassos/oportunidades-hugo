"""Avaliação determinística e explicável das vagas para o perfil de Hugo.

Este módulo usa somente dados fornecidos pela vaga. Ausências permanecem
"desconhecido" e nunca são convertidas em elegibilidade positiva.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

RAIZ = Path(__file__).parent
PERFIL_PADRAO = RAIZ / "config" / "perfil_hugo.json"


def carregar_perfil(caminho: Path = PERFIL_PADRAO) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def texto_da_vaga(vaga: dict) -> str:
    campos = (
        "titulo", "empresa", "cidade", "descricao", "responsabilidades",
        "requisitos_obrigatorios", "requisitos_preferenciais",
        "competencias_tecnicas", "competencias_tecnicas_originais",
        "tipo_vinculo", "tipo_contrato", "modalidade", "jornada",
    )
    partes = []
    for campo in campos:
        valor = vaga.get(campo)
        if isinstance(valor, list):
            partes.extend(str(item) for item in valor)
        elif valor is not None:
            partes.append(str(valor))
    return " ".join(partes).casefold()


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip())


def avaliar_localidade(vaga: dict, perfil: dict) -> tuple[str, str]:
    cidade = normalizar(str(vaga.get("cidade") or "")).casefold()
    modalidade = vaga.get("modalidade")
    locais = perfil["preferencias"]["localidades_prioritarias"]
    if modalidade == "remoto" or "remoto" in cidade:
        elegibilidade = vaga.get("elegibilidade_portugal")
        if elegibilidade == "confirmada":
            return "favoravel", "Remoto elegível para Portugal confirmado."
        if elegibilidade in (None, "nao_verificada", "provavel"):
            return "por_confirmar", "Remoto indicado, mas elegibilidade em Portugal não confirmada."
    if any(local in cidade for local in locais):
        return "favoravel", f"Localização indicada em {vaga.get('cidade')}."
    if cidade:
        return "menos_favoravel", f"Localização indicada fora do recorte preferido: {vaga.get('cidade')}."
    return "desconhecida", "Localização não disponível."


def requisitos(vaga: dict) -> tuple[list[str], list[str], list[str]]:
    obrigatorios = vaga.get("requisitos_obrigatorios")
    preferenciais = vaga.get("requisitos_preferenciais")
    conhecidos_obrigatorios = obrigatorios if isinstance(obrigatorios, list) else []
    conhecidos_preferenciais = preferenciais if isinstance(preferenciais, list) else []
    desconhecidos = []
    if not isinstance(obrigatorios, list) and "requisitos" not in vaga:
        desconhecidos.append("Requisitos obrigatórios")
    if not isinstance(preferenciais, list) and "requisitos" not in vaga:
        desconhecidos.append("Requisitos preferenciais")
    return conhecidos_obrigatorios, conhecidos_preferenciais, desconhecidos


def impedimentos_obrigatorios(vaga: dict) -> list[str]:
    """Só cria impedimentos quando o próprio documento informa o requisito."""
    obrigatorios, _, _ = requisitos(vaga)
    impedimentos = []
    texto = " ".join(str(item) for item in obrigatorios).casefold()
    if re.search(r"doutorados?\s+h[aá]\s+mais de\s+5\s+anos|mais de cinco anos.*doutor|doutorado.*mais de cinco anos", texto):
        impedimentos.append(
            "Requisito explícito: Doutorado há mais de cinco anos. Hugo concluiu o doutorado em 2023."
        )
    if re.search(r"certific[aã]o obrigatória|certifica[cç][aã]o exigida", texto):
        impedimentos.append("Requisito obrigatório de certificação explícito.")
    if re.search(r"não.*trabalho remoto|presencial obrigat", texto):
        impedimentos.append("Regime presencial indicado como obrigatório.")
    return impedimentos


def afinidade_profissional(vaga: dict, perfil: dict) -> tuple[str, list[str], list[str]]:
    texto = texto_da_vaga(vaga)
    competencias = perfil["competencias_confirmadas"]
    relacionadas = []
    evidencias = []
    sinonimos = {
        "otimizacao matematica": ("otimizacao", "optimization", "otimiza"),
        "modelagem matematica e computacional": ("modelagem", "modelizacao", "simulation"),
        "sistemas eletricos e energeticos": ("sistema eletrico", "sistemas de energia", "energet", "energia"),
        "simulacao computacional": ("simulacao", "simulation", "fem"),
        "python cientifico": ("python",),
        "pyomo": ("pyomo",),
        "pesquisa e desenvolvimento": ("pesquisa", "investigacao", "research", "r&d"),
    }
    for competencia in competencias:
        termos = sinonimos.get(competencia, (competencia,))
        if any(normalizar(str(t).casefold()) in texto for t in termos):
            relacionadas.append(competencia)
            evidencias.append(f"Evidência no título/área/categoria: {competencia}.")

    titulo = str(vaga.get("titulo") or "").casefold()
    formacao = perfil["formacao"]
    if any(term in titulo for term in ("sistema", "energia", "eletrica", "eletronic", "otimiz", "investigador", "pesquisa")):
        evidencias.append("Área da vaga relacionada à formação em Engenharia Elétrica.")
    if len(relacionadas) >= 2:
        nivel = "alta"
    elif relacionadas:
        nivel = "moderada"
    elif texto.strip() and any(term in texto for term in (
        "engineer", "engenheiro", "cientista", "data", "software",
        "investigador", "pesquisa", "research", "energia",
        "otimiz", "sistema", "python",
    )):
        nivel = "baixa"
    else:
        nivel = "insuficiente"
    return nivel, relacionadas, evidencias


def prazo_candidatura(vaga: dict, hoje: dt.date | None = None) -> tuple[str, str]:
    valor = vaga.get("prazo_candidatura")
    if not valor:
        data_publicada = vaga.get("data_publicacao")
        if data_publicada and re.match(r"\d{4}-\d{2}-\d{2}$", str(data_publicada)):
            return "desconhecido", "Data disponível pode ser prazo ou outra data; não foi confirmada como prazo."
        return "desconhecido", "Prazo de candidatura não disponível."
    hoje = hoje or dt.date.today()
    try:
        texto = str(valor)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", texto):
            data = dt.date.fromisoformat(texto)
        elif re.match(r"^\d{2}/\d{2}/\d{4}$", texto):
            data = dt.datetime.strptime(texto, "%d/%m/%Y").date()
        else:
            return "desconhecido", f"Prazo com formato não reconhecido: {valor}"
    except ValueError:
        return "desconhecido", f"Prazo inválido ou não confirmado: {valor}"
    if data < hoje:
        return "vencido", f"Prazo conhecido: {data.isoformat()}, vencido em relação a {hoje.isoformat()}."
    return "vigente", f"Prazo conhecido: {data.isoformat()}."


def avaliar_vaga(vaga: dict, perfil: dict | None = None, hoje: dt.date | None = None) -> dict:
    perfil = perfil or carregar_perfil()
    afinidade, relacionadas, evidencias = afinidade_profissional(vaga, perfil)
    impedimentos = impedimentos_obrigatorios(vaga)
    localidade, justificativa_local = avaliar_localidade(vaga, perfil)
    obrigatorios, preferenciais, desconhecidos = requisitos(vaga)
    prazo_estado, justificativa_prazo = prazo_candidatura(vaga, hoje)

    if impedimentos:
        classificacao = "baixa_compatibilidade"
        nivel_afinidade = afinidade
        justificativa = "Há impedimento obrigatório comprovado; a afinidade técnica não elimina a barreira."
    elif prazo_estado == "vencido":
        classificacao = "baixa_compatibilidade"
        nivel_afinidade = afinidade
        justificativa = "Prazo de candidatura conhecido como vencido."
    elif not vaga.get("descricao") and not obrigatorios and not preferenciais and not vaga.get("competencias_tecnicas"):
        classificacao = "precisa_verificar"
        nivel_afinidade = "insuficiente"
        justificativa = "Informações insuficientes para uma recomendação fundamentada."
    elif afinidade in ("alta", "moderada") and localidade != "desconhecida" and prazo_estado != "vencido" and not desconhecidos:
        classificacao = "prioritaria"
        nivel_afinidade = afinidade
        justificativa = "Afinidade útil com informações suficientes e sem impedimento obrigatório conhecido."
    elif afinidade in ("alta", "moderada") and not impedimentos:
        classificacao = "precisa_verificar"
        nivel_afinidade = afinidade
        justificativa = "Há afinidade relevante, mas requisitos, localização ou prazo ainda precisam ser confirmados."
    elif afinidade == "baixa":
        classificacao = "baixa_compatibilidade"
        nivel_afinidade = afinidade
        justificativa = "A correspondência disponível é limitada."
    else:
        classificacao = "precisa_verificar"
        nivel_afinidade = afinidade
        justificativa = "Informações insuficientes para uma recomendação fundamentada."

    return {
        "classificacao": classificacao,
        "afinidade": nivel_afinidade,
        "competencias_relacionadas": relacionadas,
        "evidencias": evidencias,
        "impedimentos_obrigatorios": impedimentos,
        "requisitos_obrigatorios": obrigatorios,
        "requisitos_preferenciais": preferenciais,
        "informacoes_desconhecidas": desconhecidos + (
            ["Localização"] if localidade == "desconhecida" else []
        ) + (
            ["Prazo de candidatura"] if prazo_estado == "desconhecido" else []
        ),
        "localizacao": localidade,
        "justificativa_local": justificativa_local,
        "prazo": prazo_estado,
        "justificativa_prazo": justificativa_prazo,
        "justificativa": justificativa,
    }
