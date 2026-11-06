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

import requests

from .base import make_vaga

API_URL = "https://www.inesctec.pt/websiteAPI/oportunidades/editaisativos"
DETALHE_URL = "https://www.inesctec.pt/editais/pt/{ref}"


def fetch() -> list[dict]:
    resp = requests.get(API_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    editais = resp.json()

    vagas = []
    for e in editais:
        ref = e.get("idEdital", "")
        titulo = e.get("areaTrabalhoPT") or e.get("areaTrabalhoEN") or ref
        centro = e.get("centroPT") or e.get("centroEN") or ""
        local = (e.get("local") or "").strip() or "Porto"
        vagas.append(
            make_vaga(
                titulo=f"{titulo} ({ref})",
                empresa="INESC TEC",
                cidade=local,
                link=DETALHE_URL.format(ref=ref),
                fonte="inesctec",
                categoria=centro,
                data_publicacao=e.get("candidaturaFim"),
            )
        )
    return vagas


if __name__ == "__main__":
    import json

    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
