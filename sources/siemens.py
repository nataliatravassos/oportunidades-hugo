"""
Siemens — portal de carreiras (jobs.siemens.com), migrado para um novo
portal em 2026 (o antigo link redireciona pra cá automaticamente).

A busca usa dois campos select2 (autocomplete do tipo "digita e escolhe
uma opção da lista", não dá pra simplesmente preencher um `<select>`):
primeiro "País / região" (escolhe "Portugal"), o que libera um segundo
campo "Estado/Província/Município" (escolhe "Porto"). Only depois de
escolher as duas opções clicando nas sugestões (não só digitando) os
filtros realmente aplicam — por isso o scraper clica explicitamente em
cada sugestão, em vez de tentar atalhos de URL.

A lista de resultados é paginada (6 por página) com um botão
"próxima página" (`.paginationNextLink`).
"""

from __future__ import annotations

from .base import make_vaga
from .playwright_utils import clicar_se_existir, nova_pagina

URL = "https://jobs.siemens.com/pt_PT/externaljobs"
MAX_PAGINAS = 20


def _selecionar_select2(page, *, placeholder_aprox: str, texto_opcao: str) -> None:
    """Clica num campo select2 pelo texto do placeholder visível, digita
    `texto_opcao` e clica na sugestão exata que aparece."""
    campo = page.get_by_text(placeholder_aprox, exact=False).first
    campo.click()
    page.keyboard.type(texto_opcao)
    opcao = page.locator(
        f'li.select2-results__option[role="option"]:text-is("{texto_opcao}")'
    ).first
    opcao.wait_for(state="visible", timeout=10000)
    opcao.click()


def _extrair_pagina(page) -> list[dict]:
    cards = page.locator("article.article--result")
    total = cards.count()
    vagas = []
    for i in range(total):
        card = cards.nth(i)
        a = card.locator("a.link").first
        if a.count() == 0:
            continue
        href = a.get_attribute("href")
        titulo_el = card.locator("h3").first
        titulo = titulo_el.inner_text().strip() if titulo_el.count() else None
        if not titulo or not href:
            continue

        cidade_el = card.locator(".list-item-location").first
        cidade = cidade_el.inner_text().strip() if cidade_el.count() else None

        categoria_el = card.locator(".list-item-family").first
        categoria = categoria_el.inner_text().strip() if categoria_el.count() else None

        jobid_el = card.locator(".list-item-jobId").first
        jobid = jobid_el.inner_text().strip() if jobid_el.count() else None

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="Siemens",
                cidade=cidade,
                link=href,
                fonte="siemens",
                categoria=categoria or jobid,
            )
        )
    return vagas


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")

        clicar_se_existir(page, 'button:has-text("Accept")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Aceitar")', timeout=2000)

        _selecionar_select2(page, placeholder_aprox="País / região", texto_opcao="Portugal")
        _selecionar_select2(
            page, placeholder_aprox="Estado/Província/Município", texto_opcao="Porto"
        )

        page.locator('button:has-text("Pesquisar")').first.click()
        page.wait_for_selector("article.article--result", timeout=20000)
        page.wait_for_timeout(800)

        todas = list(_extrair_pagina(page))

        pagina_atual = 1
        while pagina_atual < MAX_PAGINAS:
            proximo = page.locator(".list-controls__pagination__item.paginationNextLink a").first
            if proximo.count() == 0:
                break
            try:
                proximo.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(1200)
            page.wait_for_selector("article.article--result", timeout=15000)
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
