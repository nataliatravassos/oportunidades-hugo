"""
FCT (Fundação para a Ciência e a Tecnologia) — lista de concursos abertos.

Esses concursos (CEEC, RESTART, projetos de investigação, etc.) não são
amarrados a uma cidade — qualquer instituto de Portugal pode concorrer,
incluindo institutos no Porto. Por isso essas vagas não passam pelo filtro
de região: elas aparecem sempre na lista final, marcadas com
cidade="Portugal (nacional)", pra você e o Hugo decidirem se algum interessa.

A página é renderizada no servidor (HTML estático), então um
`requests.get()` simples funciona bem aqui.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import make_vaga

URL = "https://www.fct.pt/concursos/"


def fetch() -> list[dict]:
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    vagas = []
    links = soup.select('a[href*="/concursos/"]')
    vistos = set()
    for a in links:
        href = a.get("href", "")
        if href.rstrip("/").endswith("/concursos") or "/en/" in href:
            continue
        if href in vistos:
            continue
        vistos.add(href)

        titulo_el = a.select_one(".calendar__title")
        if not titulo_el:
            continue
        titulo = re.sub(r"\s+", " ", titulo_el.get_text(strip=True))

        mes_el = a.select_one(".month")
        prazo = re.sub(r"\s+", " ", mes_el.get_text(strip=True)) if mes_el else None

        link = href if href.startswith("http") else f"https://www.fct.pt{href}"

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="FCT",
                cidade="Portugal (nacional)",
                link=link,
                fonte="fct",
                categoria="Concurso FCT",
                data_publicacao=prazo,
            )
        )
    return vagas


if __name__ == "__main__":
    import json

    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
