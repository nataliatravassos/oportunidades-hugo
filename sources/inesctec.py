"""
INESC TEC — lista de editais abertos (bolsas, contratos, etc.).

O site carrega a tabela de oportunidades via uma API JSON simples, então
esse módulo não precisa de navegador: um `requests.get()` resolve.
A API foi descoberta inspecionando as chamadas de rede feitas pela página
https://www.inesctec.pt/oportunidades/oportunidades.html em novembro/2026.
Se a FONTE parar de funcionar, o primeiro passo é abrir essa página no
navegador com as ferramentas de desenvolvedor abertas (aba "Network") e
procurar de novo por uma chamada a "websiteAPI".
"""

from __future__ import annotations

import re

import requests

from .base import EstadoColeta, ResultadoColeta, make_vaga

API_URL = "https://www.inesctec.pt/websiteAPI/oportunidades/editaisativos"
DETALHE_URL = "https://www.inesctec.pt/editais/pt/{ref}"


def fetch() -> ResultadoColeta:
    resp = requests.get(API_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    if resp.url.rstrip("/") != API_URL:
        return ResultadoColeta(EstadoColeta.FALHA, motivo="Redirecionamento inesperado da API de editais")
    editais = resp.json()
    if not isinstance(editais, list):
        return ResultadoColeta(EstadoColeta.FALHA, motivo="A API não devolveu uma lista de editais")
    if not editais:
        return ResultadoColeta(
            EstadoColeta.ZERO, motivo="A API de editais ativos devolveu uma lista vazia", paginas=1,
        )

    vagas = []
    invalidos = 0
    for e in editais:
        ref = e.get("idEdital") if isinstance(e, dict) else None
        if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9-]+", ref):
            invalidos += 1
            continue
        titulo = e.get("areaTrabalhoPT") or e.get("areaTrabalhoEN") or ref
        centro = e.get("centroPT") or e.get("centroEN") or ""
        local = e.get("local") or "Porto"
        if not all(isinstance(valor, str) for valor in (titulo, centro, local)):
            invalidos += 1
            continue
        vagas.append(
            make_vaga(
                titulo=f"{titulo} ({ref})",
                empresa="INESC TEC",
                cidade=local.strip() or "Porto",
                link=DETALHE_URL.format(ref=ref),
                fonte="inesctec",
                categoria=centro,
                data_publicacao=None,
                prazo_candidatura=e.get("candidaturaFim"),
            )
        )
    problemas = [f"{invalidos} edital(is) com formato inválido"] if invalidos else []
    return ResultadoColeta.avaliar(vagas, problemas, cobertura="Lista da API de editais ativos integralmente processada")


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
