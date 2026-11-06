"""
FedEx — portal de carreiras (careers.fedex.com).

Usa a busca por localização embutida no próprio site (parâmetro
`location_name` na URL), que já devolve as vagas mais próximas de Porto,
Portugal, ordenadas por distância. A lista é paginada (25 por página); o
scraper segue os links de paginação numerados até não haver mais.
"""

from __future__ import annotations

import logging

from .base import make_vaga
from .playwright_utils import nova_pagina

logger = logging.getLogger(__name__)

URL = "https://careers.fedex.com/jobs?location_name=Porto%2C%20Portugal&location_type=2"
MAX_PAGINAS = 10


def _extrair_pagina(page) -> list[dict]:
    itens = page.locator("ul.results-list > li")
    total = itens.count()
    vagas = []
    for i in range(total):
        item = itens.nth(i)
        link_el = item.locator(".results-list__item-title--link").first
        if link_el.count() == 0:
            continue
        titulo = link_el.inner_text().strip()
        href = link_el.get_attribute("href")
        local_el = item.locator(".results-list__item-street--label").first
        cidade = local_el.inner_text().strip() if local_el.count() else None
        tipo_el = item.locator(".results-list__item-employment-type").first
        tipo = None
        if tipo_el.count():
            tipo = tipo_el.inner_text().strip() or None
        ref_el = item.locator(".reference").first
        ref = ref_el.inner_text().strip() if ref_el.count() else None

        if not href:
            continue
        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="FedEx",
                cidade=cidade,
                link=href,
                fonte="fedex",
                categoria=ref,
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("ul.results-list > li", timeout=20000)
        page.wait_for_timeout(500)

        todas = list(_extrair_pagina(page))

        pagina_atual = 1
        while pagina_atual < MAX_PAGINAS:
            proxima = page.locator(f'a:has-text("{pagina_atual + 1}")').first
            if proxima.count() == 0:
                break
            try:
                proxima.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(1200)
            page.wait_for_selector("ul.results-list > li", timeout=15000)
            pagina_atual += 1
            todas.extend(_extrair_pagina(page))

        # remove duplicados (mesmo link)
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
