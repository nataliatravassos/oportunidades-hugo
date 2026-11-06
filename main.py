#!/usr/bin/env python3
"""
Orquestrador: roda todas as fontes em sources/, junta os resultados,
filtra pela região do Porto e salva em data/vagas.json e data/vagas.md.

Uso:
    python main.py

Pensado para rodar todo dia via GitHub Actions (veja
.github/workflows/daily.yml), mas funciona normalmente rodando na mão
também — útil pra testar uma fonte nova ou debugar.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import logging
import sys
from pathlib import Path

from config import FONTES, eh_regiao_porto

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout
)
logger = logging.getLogger("main")

RAIZ = Path(__file__).parent
PASTA_DADOS = RAIZ / "data"

# Fontes cuja busca já é nacional por natureza (não tem como/não faz
# sentido filtrar por cidade) — essas vagas entram sempre, sem passar
# pelo filtro de região do Porto.
FONTES_SEM_FILTRO_REGIAO = {"fct", "outros_institutos"}

# Ordem de prioridade pra ordenar o resultado final: vagas de escritório
# primeiro (mais alinhadas ao perfil do Hugo), depois as indefinidas,
# depois as operacionais (chão de fábrica/loja, ficam por último mas não
# são escondidas — ele decide).
ORDEM_CLASSIFICACAO = {"escritorio": 0, "indefinido": 1, "operacional": 2}


def rodar_fonte(nome: str) -> list[dict]:
    """Importa sources/<nome>.py e chama fetch(), isolando erros.

    Se uma fonte quebrar (site mudou de layout, timeout, etc.), isso é
    logado e o resto do programa continua rodando normalmente — uma
    fonte com problema não deve impedir as outras 10 de funcionar.
    """
    try:
        modulo = importlib.import_module(f"sources.{nome}")
    except Exception:
        logger.exception("Falha ao importar sources.%s", nome)
        return []

    try:
        vagas = modulo.fetch()
    except Exception:
        logger.exception("Falha ao buscar vagas em '%s'", nome)
        return []

    logger.info("%s: %d vaga(s) encontrada(s)", nome, len(vagas))
    return vagas


def filtrar_e_ordenar(vagas: list[dict]) -> list[dict]:
    filtradas = [
        v
        for v in vagas
        if v["fonte"] in FONTES_SEM_FILTRO_REGIAO or eh_regiao_porto(v.get("cidade"))
    ]
    filtradas.sort(
        key=lambda v: (
            ORDEM_CLASSIFICACAO.get(v["classificacao"], 99),
            v["empresa"].lower(),
            v["titulo"].lower(),
        )
    )
    return filtradas


def salvar_json(vagas: list[dict]) -> Path:
    PASTA_DADOS.mkdir(exist_ok=True)
    caminho = PASTA_DADOS / "vagas.json"
    payload = {
        "atualizado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "total": len(vagas),
        "vagas": vagas,
    }
    caminho.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return caminho


def salvar_markdown(vagas: list[dict]) -> Path:
    """Tabela em Markdown, só pra dar pra abrir e ler direto no GitHub
    sem precisar de nenhuma ferramenta especial, enquanto o formato
    final de visualização não é decidido."""
    PASTA_DADOS.mkdir(exist_ok=True)
    caminho = PASTA_DADOS / "vagas.md"

    agora = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    linhas = [
        "# Oportunidades — Porto e região",
        "",
        f"Atualizado em {agora} · {len(vagas)} vaga(s)",
        "",
        "Gerado automaticamente. Classificação é só uma estimativa por "
        "palavra-chave no título — confira a vaga antes de descartar.",
        "",
    ]

    nomes_secao = {
        "escritorio": "## Escritório / técnico (provável)",
        "indefinido": "## Não dá pra saber só pelo título",
        "operacional": "## Operacional (provável ficar muito em pé)",
    }
    for classe in ("escritorio", "indefinido", "operacional"):
        do_grupo = [v for v in vagas if v["classificacao"] == classe]
        if not do_grupo:
            continue
        linhas.append(nomes_secao[classe])
        linhas.append("")
        linhas.append("| Cargo | Empresa | Cidade | Tipo | Link |")
        linhas.append("|---|---|---|---|---|")
        for v in do_grupo:
            tipo = v.get("tipo_contrato") or "—"
            cidade = v.get("cidade") or "—"
            linhas.append(
                f"| {v['titulo']} | {v['empresa']} | {cidade} | {tipo} | [abrir]({v['link']}) |"
            )
        linhas.append("")

    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def main() -> None:
    todas: list[dict] = []
    for nome in FONTES:
        todas.extend(rodar_fonte(nome))

    logger.info("Total bruto (antes do filtro de região): %d", len(todas))

    finais = filtrar_e_ordenar(todas)
    logger.info("Total final (depois do filtro de região): %d", len(finais))

    caminho_json = salvar_json(finais)
    caminho_md = salvar_markdown(finais)
    logger.info("Salvo em %s e %s", caminho_json, caminho_md)


if __name__ == "__main__":
    main()
