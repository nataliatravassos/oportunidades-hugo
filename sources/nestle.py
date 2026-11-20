"""
Nestlé — portal de carreiras (www.nestle.com/jobs), widget SearchStax.

O formulário de busca usa um `<select>` comum para "Country or Region",
mas ele não reage a eventos de teclado/clique normais do Playwright em
alguns casos (framework reativo que só escuta o evento "change" do
próprio elemento) — por isso o valor é setado via JavaScript
(`select_option`, que já dispara "change" corretamente no Playwright,
então aqui basta usar a API nativa).

O campo "Location" dessa busca lista só cidades específicas onde a
Nestlé tem vagas (ex.: "Avanca", "Braga", "Linda a Velha") — não existe
uma opção "Porto" en quanto tal, já que o Porto raramente aparece com
vagas de escritório da Nestlé diretamente. Por isso aqui a gente busca
TODAS as vagas de Portugal (sem filtrar localização no site) e deixa o
filtro de região do main.py decidir quais ficam, usando a cidade de cada
vaga.

A lista é paginada (10 por página) com um pager estilo Drupal
(`.pager__item--next`).
"""

from __future__ import annotations

from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, links_dos_cartoes, nova_pagina,
)

URL = "https://www.nestle.com/jobs"
MAX_PAGINAS = 10
SELETOR_CARD = ".jobs-card"


def _extrair_pagina(page) -> list[dict]:
    cards = page.locator(SELETOR_CARD)
    total = cards.count()
    vagas = []
    for i in range(total):
        card = cards.nth(i)
        a = card.locator("a").first
        if a.count() == 0:
            continue
        href = a.get_attribute("href")
        titulo_el = card.locator(".jobs-title").first
        titulo = None
        if titulo_el.count():
            # remove o texto de acessibilidade "(opens in new tab)"
            titulo = titulo_el.inner_text().split("(opens in new tab)")[0].strip()
        if not titulo or not href:
            continue

        cidade_el = card.locator(".jobs-location").first
        cidade = cidade_el.inner_text().strip() if cidade_el.count() else None

        categoria_el = card.locator(".jobs-career-area").first
        categoria = categoria_el.inner_text().strip() if categoria_el.count() else None

        tipo_el = card.locator(".jobs-type").first
        tipo = tipo_el.inner_text().strip() if tipo_el.count() else None

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="Nestlé",
                cidade=cidade,
                link=url_absoluta(href, page.url),
                fonte="nestle",
                categoria=categoria,
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        clicar_se_existir(page, 'button:has-text("Accept All Cookies")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Accept")', timeout=2000)

        # Usa o segundo formulário da página (o widget completo, com
        # paginação) em vez do atalho no topo da página.
        selects = page.locator('select[name="country"]')
        select_pais = selects.last
        select_pais.wait_for(state="visible", timeout=15000)
        select_pais.select_option("PT")

        botoes_busca = page.locator('button:has-text("Search jobs")')
        anteriores = links_dos_cartoes(page, SELETOR_CARD)
        botoes_busca.last.click()
        esperar_resultados(page, SELETOR_CARD, anteriores)

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator(".pager__item--next a").first,
            MAX_PAGINAS,
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
