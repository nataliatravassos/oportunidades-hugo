"""Valida a base de vagas e instala apenas arquivos completamente preparados."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from sources.base import url_absoluta
from sources.ciclo import SITUACOES_VALIDAS
from sources.fedex_links import url_vaga_fedex

SECOES = {
    "escritorio": "## Escritório / técnico (provável)",
    "indefinido": "## Não dá pra saber só pelo título",
    "operacional": "## Operacional (provável ficar muito em pé)",
}

CAMPOS_CICLO_OPCIONAIS = (
    "situacao", "primeira_observacao", "ultima_observacao",
    "ultima_verificacao", "evidencia_encerramento",
)
def validar_vaga(vaga: dict, *, legado: bool = False, preservada: bool = False) -> dict:
    if not isinstance(vaga, dict):
        raise ValueError("Registo não é um objeto")
    for campo in ("fonte", "titulo", "empresa"):
        valor = vaga.get(campo)
        if not isinstance(valor, str) or not valor.strip():
            raise ValueError(f"Campo obrigatório inválido: {campo}")
    for campo in ("cidade", "categoria", "tipo_contrato", "data_publicacao", "coletado_em",
                  "evidencia_modalidade", "evidencia_elegibilidade",
                  "primeira_observacao", "ultima_observacao", "ultima_verificacao",
                  "evidencia_encerramento"):
        valor = vaga.get(campo)
        if valor is not None and not isinstance(valor, str):
            raise ValueError(f"Campo inválido: {campo}")
    classificacao = vaga.get("classificacao")
    if not isinstance(classificacao, str) or classificacao not in SECOES:
        raise ValueError("Classificação inválida")
    if "verificacao_pendente" in vaga and type(vaga["verificacao_pendente"]) is not bool:
        raise ValueError("Estado da verificação inválido")
    if "situacao" in vaga and vaga["situacao"] not in SITUACOES_VALIDAS:
        raise ValueError("Situação de ciclo de vida inválida")
    if "modalidade" in vaga and vaga["modalidade"] not in ("remoto", "hibrido", "presencial", "desconhecido"):
        raise ValueError("Modalidade inválida")
    if "elegibilidade_portugal" in vaga and vaga["elegibilidade_portugal"] not in (
        "confirmada", "provavel", "nao_verificada", "inelegivel",
    ):
        raise ValueError("Elegibilidade em Portugal inválida")
    for campo_data in ("coletado_em", "primeira_observacao", "ultima_observacao", "ultima_verificacao"):
        if vaga.get(campo_data):
            _data_com_fuso(vaga[campo_data])
    href = vaga.get("link")
    if vaga["fonte"] == "fedex":
        link = url_vaga_fedex(href, legado=legado, referencia=vaga.get("categoria"))
        if not link and legado and isinstance(href, str) and href:
            return {**vaga, "link": None, "link_original": href}
        if not link and (legado or preservada) and href is None and isinstance(vaga.get("link_original"), str):
            return vaga
    else:
        link = url_absoluta(href)
    if not link:
        raise ValueError("Link de candidatura inválido")
    return {**vaga, "link": link}


def _data_com_fuso(valor: str) -> dt.datetime:
    if not isinstance(valor, str):
        raise ValueError("Carimbo de data inválido")
    data = dt.datetime.fromisoformat(valor)
    if data.utcoffset() is None:
        raise ValueError("Carimbo de data sem fuso")
    return data


def validar_payload(dados: dict, *, legado: bool = False) -> list[dict]:
    if not isinstance(dados, dict) or not isinstance(dados.get("vagas"), list):
        raise ValueError("Formato inválido para vagas.json")
    if type(dados.get("total")) is not int or dados["total"] != len(dados["vagas"]):
        raise ValueError("Total incompatível com a lista de vagas")
    _data_com_fuso(dados.get("atualizado_em"))
    return [validar_vaga(vaga, legado=legado, preservada=True) for vaga in dados["vagas"]]


def carregar_base(pasta: Path) -> tuple[dict | None, list[dict]]:
    caminho = pasta / "vagas.json"
    if not caminho.exists():
        if (pasta / "vagas.md").exists():
            raise ValueError("A tabela anterior existe, mas vagas.json está ausente")
        return None, []
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return dados, validar_payload(dados, legado=True)


def _celula(valor: str) -> str:
    return " ".join(valor.split()).replace("\\", "\\\\").replace("|", "\\|")


def _ultima_data_vaga(vaga: dict) -> str:
    """Devolve a data mais recente disponível para exibir na tabela."""
    for campo in ("ultima_observacao", "coletado_em"):
        valor = vaga.get(campo)
        if valor:
            try:
                return _data_com_fuso(valor).astimezone(dt.timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
            except (ValueError, TypeError):
                continue
    return "Sem data registada"


def _linha_tabela(vaga: dict, *, mostrar_situacao: bool = False) -> str:
    situacao = vaga.get("situacao", "observada")
    ultima = _ultima_data_vaga(vaga)
    if situacao == "por_confirmar" or vaga.get("verificacao_pendente"):
        ultima += " · por confirmar"
    elif situacao == "encerrada":
        evidencia = vaga.get("evidencia_encerramento") or "encerrada"
        ultima += f" · encerrada ({_celula(evidencia)})"
    campos = (
        vaga["titulo"], vaga["empresa"],
        vaga.get("cidade") or "—",
        vaga.get("tipo_contrato") or "—",
        ultima,
    )
    link = vaga["link"]
    destino = f"[abrir](<{link}>)" if link else "Link por confirmar"
    return "| " + " | ".join(map(_celula, campos)) + f" | {destino} |"


def renderizar_markdown(dados: dict) -> str:
    agora = dt.datetime.fromisoformat(dados["atualizado_em"]).astimezone(dt.timezone.utc)
    todas = dados["vagas"]
    ativas = [v for v in todas if v.get("situacao", "observada") != "encerrada"]
    encerradas = [v for v in todas if v.get("situacao") == "encerrada"]
    linhas = [
        "# Oportunidades — Porto e região",
        "",
        f"Atualizado em {agora:%Y-%m-%d %H:%M} UTC · {len(ativas)} vaga(s) ativa(s)",
        "",
        "Gerado automaticamente. Classificação é só uma estimativa por "
        "palavra-chave no título — confira a vaga antes de descartar.",
        "",
        "**Filtros de situação:** observada · por confirmar · encerrada",
        "",
    ]
    for classe, secao in SECOES.items():
        vagas = [v for v in ativas if v["classificacao"] == classe]
        if not vagas:
            continue
        linhas.extend([
            secao, "", "| Cargo | Empresa | Cidade | Tipo | Última vez vista | Link |",
            "|---|---|---|---|---|---|",
        ])
        for vaga in vagas:
            linhas.append(_linha_tabela(vaga))
        linhas.append("")
    if encerradas:
        linhas.extend([
            "## Encerradas (histórico)",
            "",
            "| Cargo | Empresa | Cidade | Tipo | Última vez vista | Link |",
            "|---|---|---|---|---|---|",
        ])
        for vaga in encerradas:
            linhas.append(_linha_tabela(vaga))
        linhas.append("")
    return "\n".join(linhas)


def _json(dados: dict) -> str:
    return json.dumps(dados, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def publicar(pasta: Path, dados: dict | None, diagnostico: dict) -> None:
    conteudos = {}
    if dados is not None:
        json_vagas = _json(dados)
        if validar_payload(json.loads(json_vagas)) != dados["vagas"]:
            raise ValueError("A lista a publicar contém links sem normalização")
        markdown = renderizar_markdown(dados)
        vagas_renderizadas = sum(linha.endswith((">) |", "Link por confirmar |")) for linha in markdown.splitlines())
        if vagas_renderizadas != dados["total"]:
            raise ValueError(f"O Markdown não contém uma linha por vaga ({vagas_renderizadas} vs {dados['total']})")
        conteudos.update({"vagas.md": markdown, "vagas.json": json_vagas})
    conteudos["coleta.json"] = _json(diagnostico)

    pasta.mkdir(parents=True, exist_ok=True)
    # Prepare todos os arquivos no mesmo volume antes de substituir o primeiro.
    # No Actions, os três arquivos passam a ser públicos no mesmo commit.
    with TemporaryDirectory(dir=pasta, prefix=".coleta-") as temporario:
        etapas = Path(temporario)
        for nome, conteudo in conteudos.items():
            with (etapas / nome).open("wb") as arquivo:
                arquivo.write(conteudo.encode("utf-8"))
                arquivo.flush()
                os.fsync(arquivo.fileno())
            anterior = pasta / nome
            if anterior.exists():
                shutil.copyfile(anterior, etapas / (nome + ".anterior"))

        instalados = []
        try:
            for nome in conteudos:
                os.replace(etapas / nome, pasta / nome)
                instalados.append(nome)
        except OSError:
            for nome in reversed(instalados):
                copia = etapas / (nome + ".anterior")
                if copia.exists():
                    os.replace(copia, pasta / nome)
                else:
                    (pasta / nome).unlink()
            raise
