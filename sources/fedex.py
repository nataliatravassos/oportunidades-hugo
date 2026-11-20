"""
FedEx — portal de carreiras (careers.fedex.com).

Usa a busca por localização embutida no próprio site (parâmetro
`location_name` na URL), que já devolve as vagas mais próximas de Porto,
Portugal, ordenadas por distância. A lista é paginada (25 por página); o
scraper segue os links de paginação numerados até não haver mais.
"""

from __future__ import annotations

import logging

from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, coletar_paginas, nova_pagina,
)

logger = logging.getLogger(__name__)

URL = "https://careers.fedex.com/jobs?location_name=Porto%2C%20Portugal&location_type=2"
MAX_PAGINAS = 10
SELETOR_CARD = "ul.results-list > li"


def _extrair_pagina(page) -> list[dict]:
    itens = page.locator(SELETOR_CARD)
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
                link=url_absoluta(href, page.url),
                fonte="fedex",
                categoria=ref,
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)
        page.wait_for_selector(SELETOR_CARD, timeout=20000)

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator(f'a:text-is("{numero + 1}")').first,
            MAX_PAGINAS,
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
