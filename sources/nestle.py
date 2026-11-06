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

from .base import make_vaga
from .playwright_utils import clicar_se_existir, nova_pagina

URL = "https://www.nestle.com/jobs"
MAX_PAGINAS = 10


def _extrair_pagina(page) -> list[dict]:
    cards = page.locator(".jobs-card")
    total = cards.count()
    vagas = []
    for i in range(total):
        card = cards.nth(i)
        a = card.locator("a").first
        if a.count() == 0:
            continue
        href = a.get_attribute("href")
        if href:
            href = href.split("?")[0]
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
                link=href,
                fonte="nestle",
                categoria=categoria,
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")

        clicar_se_existir(page, 'button:has-text("Accept All Cookies")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Accept")', timeout=2000)

        # Usa o segundo formulário da página (o widget completo, com
        # paginação) em vez do atalho no topo da página.
        selects = page.locator('select[name="country"]')
        select_pais = selects.last
        select_pais.wait_for(state="visible", timeout=15000)
        select_pais.select_option("PT")

        botoes_busca = page.locator('button:has-text("Search jobs")')
        botoes_busca.last.click()

        page.wait_for_selector(".jobs-card", timeout=20000)
        page.wait_for_timeout(800)

        todas = list(_extrair_pagina(page))

        pagina_atual = 1
        while pagina_atual < MAX_PAGINAS:
            proximo = page.locator(".pager__item--next a").first
            if proximo.count() == 0:
                break
            try:
                proximo.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(1200)
            page.wait_for_selector(".jobs-card", timeout=15000)
            pagina_atual += 1
            novas = _extrair_pagina(page)
            if not novas:
                break
            todas.extend(novas)

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

    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
