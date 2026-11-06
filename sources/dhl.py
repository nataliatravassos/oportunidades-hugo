"""
DHL — portal de carreiras (careers.dhl.com).

Esse site não aceita um parâmetro de localização direto na URL (testado:
não existe um `?location=Porto` que funcione de forma confiável) — a busca
por local é feita por um campo de autocomplete que sugere localizações
reais (ex.: "Maia, Porto, Portugal") e, ao escolher uma, ativa uma busca
por raio (perímetro) de 100 km ao redor dela. O scraper reproduz esse
fluxo: digita "Porto" no campo de localização, espera a sugestão
"Maia, Porto, Portugal" aparecer e clica nela, depois clica em "Find Jobs".

Essa busca por perímetro também traz vagas fora da região (ex.: Lisboa),
então — assim como em bosch.py — a filtragem final por região fica a
cargo do main.py, usando o campo "cidade" de cada vaga.

A lista de resultados é paginada (10 por página) com links numerados,
igual ao fedex.py.
"""

from __future__ import annotations

import logging
import re

from .base import make_vaga
from .playwright_utils import clicar_se_existir, nova_pagina

logger = logging.getLogger(__name__)

URL = "https://careers.dhl.com/global/en/search-results"
LOCAL_BUSCA = "Porto"
SUGESTAO_ESPERADA = "Maia, Porto, Portugal"
MAX_PAGINAS = 10


def _extrair_pagina(page) -> list[dict]:
    itens = page.locator("li.jobs-list-item")
    total = itens.count()
    vagas = []
    for i in range(total):
        item = itens.nth(i)
        link_el = item.locator("a").first
        if link_el.count() == 0:
            continue
        href = link_el.get_attribute("href")
        titulo_el = item.locator(".job-title").first
        titulo = titulo_el.inner_text().strip() if titulo_el.count() else None
        if not titulo or not href:
            continue

        loc_el = item.locator(".job-location").first
        cidade = None
        if loc_el.count():
            cidade = re.sub(r"^\s*Location\s*", "", loc_el.inner_text().strip()).strip()

        info_el = item.locator(".job-info").first
        tipo = None
        if info_el.count():
            info_texto = re.sub(r"\s+", " ", info_el.inner_text()).strip()
            tipo = info_texto.replace("Location", "").replace(cidade or "", "").strip() or None

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="DHL",
                cidade=cidade,
                link=href if href.startswith("http") else f"https://careers.dhl.com{href}",
                fonte="dhl",
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")

        # Banner de cookies: melhor esforço, nem sempre aparece.
        clicar_se_existir(page, 'button:has-text("Accept All")', timeout=4000)

        campo_local = page.locator("#gllocationInput")
        campo_local.click()
        campo_local.fill(LOCAL_BUSCA)

        sugestao = page.locator(f'a:has-text("{SUGESTAO_ESPERADA}")').first
        sugestao.wait_for(state="visible", timeout=10000)
        sugestao.click()

        page.locator('button:has-text("Find Jobs")').first.click()
        page.wait_for_selector("li.jobs-list-item", timeout=20000)
        page.wait_for_timeout(800)

        todas = list(_extrair_pagina(page))

        pagina_atual = 1
        while pagina_atual < MAX_PAGINAS:
            proxima = page.locator(f'a.phw-s-page-number-link:has-text("{pagina_atual + 1}")').first
            if proxima.count() == 0:
                break
            try:
                proxima.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(1200)
            page.wait_for_selector("li.jobs-list-item", timeout=15000)
            pagina_atual += 1
            todas.extend(_extrair_pagina(page))

        vistos = set()
        unicas = []
        for v in todas:
            if v["link"] in vistos:
                continue
            vistos.add(v["link"])
            unicas.append(v)
        return unicas


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
