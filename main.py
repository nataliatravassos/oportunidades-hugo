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
import logging
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from config import FONTES, eh_regiao_porto
from publicacao import carregar_base, publicar, validar_vaga
from sources.base import EstadoColeta, ResultadoColeta, resumir_erro

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
FONTES_MANUAIS = {"outros_institutos"}
FALHA_TOTAL = 2


def rodar_fonte(nome: str) -> ResultadoColeta:
    try:
        modulo = importlib.import_module(f"sources.{nome}")
        resultado = modulo.fetch()
        if (
            not isinstance(resultado, ResultadoColeta)
            or not isinstance(resultado.estado, EstadoColeta)
            or not isinstance(resultado.vagas, list)
        ):
            raise ValueError("O coletor não retornou um ResultadoColeta válido")
        if resultado.estado in (EstadoColeta.COMPLETA, EstadoColeta.PARCIAL) and not resultado.vagas:
            raise ValueError("Lista vazia sem confirmação")
        if resultado.estado == EstadoColeta.ZERO and (resultado.vagas or not resultado.motivo):
            raise ValueError("Zero sem evidência explícita ou com registos")
        return resultado
    except Exception as erro:
        logger.exception("Falha na fonte %s", nome)
        return ResultadoColeta(EstadoColeta.FALHA, motivo=resumir_erro(erro))


def validar_resultado(nome: str, resultado: ResultadoColeta) -> tuple[ResultadoColeta, int]:
    if resultado.estado in (EstadoColeta.FALHA, EstadoColeta.ZERO):
        return resultado, 0
    validas = []
    erros = set()
    for vaga in resultado.vagas:
        try:
            vaga = validar_vaga(vaga)
            if vaga["fonte"] != nome:
                raise ValueError("Registo atribuído à fonte errada")
            if nome not in FONTES_SEM_FILTRO_REGIAO and not (vaga.get("cidade") or "").strip():
                raise ValueError("Localização ausente para o filtro regional")
            validas.append(vaga)
        except ValueError as erro:
            erros.add(str(erro))
    rejeitadas = len(resultado.vagas) - len(validas)
    if rejeitadas:
        problemas = [resultado.motivo] if resultado.motivo else []
        problemas.append(f"{rejeitadas} registo(s) inválido(s): {', '.join(sorted(erros))}")
        return ResultadoColeta.avaliar(validas, problemas, resultado.paginas), rejeitadas
    return replace(resultado, vagas=validas), 0


def _dados_da_vaga(vaga: dict) -> dict:
    return {campo: valor for campo, valor in vaga.items() if campo != "coletado_em"}


def _ordem(vaga: dict) -> tuple:
    return (
        ORDEM_CLASSIFICACAO[vaga["classificacao"]],
        vaga["empresa"].lower(), vaga["titulo"].lower(), vaga["fonte"], vaga["link"],
    )


def atualizar_fonte(anteriores: list[dict], locais: list[dict], estado: EstadoColeta) -> list[dict]:
    if estado == EstadoColeta.ZERO:
        return []
    if estado == EstadoColeta.FALHA:
        return anteriores
    por_link = {v["link"]: v for v in anteriores}
    if estado == EstadoColeta.COMPLETA:
        atualizadas = []
        for vaga in locais:
            anterior = por_link.get(vaga["link"])
            if anterior is not None and _dados_da_vaga(anterior) == _dados_da_vaga(vaga):
                vaga = anterior
            atualizadas.append(vaga)
        return atualizadas
    novas = []
    for vaga in locais:
        if vaga["link"] not in por_link:
            por_link[vaga["link"]] = vaga
            novas.append(vaga)
    return anteriores + novas


def main() -> int:
    anterior, vagas_anteriores = carregar_base(PASTA_DADOS)
    por_fonte = defaultdict(list)
    for vaga in vagas_anteriores:
        por_fonte[vaga["fonte"]].append(vaga)

    diagnosticos = {}
    for nome in FONTES:
        bruto = rodar_fonte(nome)
        resultado, rejeitadas = validar_resultado(nome, bruto)
        locais = [
            vaga for vaga in resultado.vagas
            if nome in FONTES_SEM_FILTRO_REGIAO or eh_regiao_porto(vaga.get("cidade"))
        ]
        anteriores = por_fonte[nome]
        publicadas = atualizar_fonte(anteriores, locais, resultado.estado)
        por_fonte[nome] = publicadas
        diagnosticos[nome] = {
            "estado": resultado.estado,
            "motivo": resultado.motivo,
            "paginas": resultado.paginas,
            "extraidas": len(bruto.vagas),
            "rejeitadas": rejeitadas,
            "observadas_na_regiao": len(locais),
            "preservadas": len(anteriores) if resultado.estado in (EstadoColeta.PARCIAL, EstadoColeta.FALHA) else 0,
            "publicadas": len(publicadas),
            "manual": nome in FONTES_MANUAIS,
        }
        logar = logger.warning if resultado.estado in (EstadoColeta.PARCIAL, EstadoColeta.FALHA) else logger.info
        logar("%s: %s, %s", nome, resultado.estado, diagnosticos[nome])

    automaticas = [item["estado"] for item in diagnosticos.values() if not item["manual"]]
    falha_total = all(estado == EstadoColeta.FALHA for estado in automaticas)
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    atualizado_em = anterior["atualizado_em"] if anterior else None
    dados = None
    if not falha_total:
        vagas = sorted(
            (vaga for grupo in por_fonte.values() for vaga in grupo),
            key=_ordem,
        )
        if anterior is None or vagas != sorted(anterior["vagas"], key=_ordem):
            atualizado_em = agora
            dados = {"atualizado_em": atualizado_em, "total": len(vagas), "vagas": vagas}
        elif not (PASTA_DADOS / "vagas.md").is_file():
            dados = anterior
    else:
        for nome, item in diagnosticos.items():
            if item["manual"]:
                item["publicadas"] = item["preservadas"] = sum(
                    vaga["fonte"] == nome for vaga in vagas_anteriores
                )

    estado = "sucesso"
    if falha_total:
        estado = "falha_total"
    elif any(item["estado"] in (EstadoColeta.FALHA, EstadoColeta.PARCIAL) for item in diagnosticos.values()):
        estado = "parcial"

    publicar(PASTA_DADOS, dados, {
        "coleta_finalizada_em": agora,
        "estado": estado,
        "dados_atualizados": dados is not None and (anterior is None or dados != anterior),
        "dados_atualizados_em": atualizado_em,
        "fontes": diagnosticos,
    })
    if falha_total:
        logger.error("Todas as fontes automáticas falharam. A base de vagas foi preservada.")
        return FALHA_TOTAL
    logger.info("Coleta %s. %d registo(s) na base.", estado, sum(map(len, por_fonte.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
