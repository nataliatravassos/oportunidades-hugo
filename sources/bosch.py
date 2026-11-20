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

from .base import ResultadoColeta, make_vaga, resumir_erro, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, esperar_resultados, links_dos_cartoes, nova_pagina,
)

logger = logging.getLogger(__name__)

URL = "https://jobs.bosch.com/en/?pages=1&country=pt"
MAX_CLIQUES_CARREGAR_MAIS = 30
SELETOR_CARD = ".M-JobSearchResultsGroup__item"

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


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        # O banner de cookies nem sempre aparece (depende de cache), então
        # isso é "melhor esforço": se não aparecer em 4s, segue em frente.
        clicar_se_existir(page, 'button:has-text("Decline all")', timeout=4000)

        esperar_resultados(page, SELETOR_CARD, [])

        problemas = []
        vagas = {}
        paginas = 0
        botao = page.locator('button:has-text("See all jobs")').first
        for cliques in range(MAX_CLIQUES_CARREGAR_MAIS + 1):
            try:
                links = links_dos_cartoes(page, SELETOR_CARD)
                extraidas = _extrair_pagina(page)
                paginas += 1
                for vaga in extraidas:
                    vagas.setdefault(vaga["link"] or vaga["titulo"], vaga)
                if len(extraidas) != len(links):
                    problemas.append(f"{len(extraidas)}/{len(links)} cartões extraídos")
                if botao.count() == 0 or not botao.is_visible() or botao.is_disabled():
                    break
                if cliques == MAX_CLIQUES_CARREGAR_MAIS:
                    problemas.append("Limite de carregamentos atingido com navegação restante")
                    break
                botao.click()
                esperar_resultados(page, SELETOR_CARD, links, crescer=True)
            except Exception as erro:
                problemas.append(f"Carregar mais: {resumir_erro(erro)}")
                break
        return ResultadoColeta.avaliar(list(vagas.values()), problemas, paginas)


def _extrair_pagina(page) -> list[dict]:
    vagas = []
    for card in page.locator(SELETOR_CARD).all():
        link_el = card.locator("a").first
        parsed = _parse_card(card.inner_text())
        if not parsed or not link_el.count():
            continue
        vagas.append(
            make_vaga(
                titulo=parsed["titulo"],
                empresa="Bosch",
                cidade=parsed["cidade"],
                link=url_absoluta(link_el.get_attribute("href"), page.url),
                fonte="bosch",
                categoria=parsed["categoria"],
                tipo_contrato=parsed.get("modo"),
                data_publicacao=parsed.get("data"),
            )
        )
    return vagas


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
