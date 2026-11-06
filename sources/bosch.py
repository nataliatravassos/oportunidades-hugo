"""
Bosch — portal de carreiras (jobs.bosch.com).

A busca por cidade exata ("Porto") costuma devolver 0 resultados porque a
Bosch não tem instalação na cidade do Porto propriamente — as vagas da
região ficam em Aveiro e Braga. Por isso aqui a gente carrega TODAS as
vagas de Portugal (sem filtrar cidade no site) e deixa o filtro de região
pro main.py aplicar depois, usando o campo "cidade" de cada vaga.

A lista carrega 8 vagas por vez; tem um botão "See all jobs" que funciona
como "carregar mais". O scraper clica nele repetidamente até não aparecer
mais vagas novas (ou até um limite de segurança).
"""

from __future__ import annotations

import logging
import re

from .base import make_vaga
from .playwright_utils import clicar_se_existir, nova_pagina

logger = logging.getLogger(__name__)

URL = "https://jobs.bosch.com/en/?pages=1&country=pt"
MAX_CLIQUES_CARREGAR_MAIS = 30

PADRAO_CARD = re.compile(
    r"^(?P<titulo>.+?)"
    r"Field of work(?P<categoria>.+?)"
    r"Bosch Location(?P<cidade>.+?)"
    r"(?P<modo>Hybrid|On-Site|Remote)?"
    r"Job posted:(?P<data>[\d/]+)$"
)


def _parse_card(texto: str) -> dict | None:
    texto = " ".join(texto.split())
    m = PADRAO_CARD.match(texto)
    if not m:
        return None
    return m.groupdict()


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")

        # O banner de cookies nem sempre aparece (depende de cache), então
        # isso é "melhor esforço": se não aparecer em 4s, segue em frente.
        clicar_se_existir(page, 'button:has-text("Decline all")', timeout=4000)

        # Espera a contagem de resultados aparecer e ser > 0 (a página
        # mostra "0 Result" por um instante enquanto carrega).
        page.wait_for_function(
            "document.body.innerText.includes('results') || "
            "document.body.innerText.includes('Result')",
            timeout=15000,
        )
        page.wait_for_timeout(1500)

        botao = page.locator('button:has-text("See all jobs")')
        cliques = 0
        while cliques < MAX_CLIQUES_CARREGAR_MAIS:
            if botao.count() == 0 or not botao.first.is_visible():
                break
            antes = page.locator(".M-JobSearchResultsGroup__item").count()
            try:
                botao.first.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(900)
            depois = page.locator(".M-JobSearchResultsGroup__item").count()
            cliques += 1
            if depois <= antes:
                break

        cards = page.locator(".M-JobSearchResultsGroup__item")
        total = cards.count()
        vagas = []
        for i in range(total):
            card = cards.nth(i)
            link_el = card.locator("a").first
            href = None
            try:
                href = link_el.get_attribute("href")
            except Exception:  # noqa: BLE001
                pass
            texto = card.inner_text()
            parsed = _parse_card(texto)
            if not parsed or not href:
                continue
            vagas.append(
                make_vaga(
                    titulo=parsed["titulo"],
                    empresa="Bosch",
                    cidade=parsed["cidade"],
                    link=href if href.startswith("http") else f"https://jobs.bosch.com{href}",
                    fonte="bosch",
                    categoria=parsed["categoria"],
                    tipo_contrato=parsed.get("modo"),
                    data_publicacao=parsed.get("data"),
                )
            )
        return vagas


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
