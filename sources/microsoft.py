"""
Microsoft — portal de carreiras (jobs.careers.microsoft.com).

Esse portal é um app React cujas classes CSS são "hasheadas" (tipo
`card-F1ebU`) e mudam a cada deploy do site — por isso aqui a gente evita
usar essas classes como seletor e prefere atributos de acessibilidade
estáveis (`role`, `aria-label`, `data-testid`), que são bem menos
prováveis de mudar.

Buscar por "Porto" direto devolveu 0 vagas (mesmo no raio máximo de
160 km) no momento em que isso foi escrito — a Microsoft tem pouquíssima
presença em escritório no Porto. Por isso aqui a gente busca por
"Portugal" (nível país, sem filtro de cidade) pra não perder vagas
remotas/híbridas que listam Portugal inteiro como localização, e deixa
o filtro de região do main.py decidir o que fica.

A lista da esquerda é paginada (10 por página) com um botão
"Next jobs" identificado por aria-label (estável).
"""

from __future__ import annotations

from .base import make_vaga
from .playwright_utils import clicar_se_existir, nova_pagina

URL = "https://jobs.careers.microsoft.com/global/en/search"
LOCAL_BUSCA = "Portugal"
MAX_PAGINAS = 10


def _extrair_pagina(page) -> list[dict]:
    cards = page.locator('[class*="cardListItem"]')
    total = cards.count()
    vagas = []
    for i in range(total):
        card = cards.nth(i)
        a = card.locator("a").first
        if a.count() == 0:
            continue
        href = a.get_attribute("href")
        texto = card.inner_text().strip()
        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        if len(linhas) < 2 or not href:
            continue
        titulo = linhas[0]
        cidade = linhas[1]

        link = href if href.startswith("http") else f"https://jobs.careers.microsoft.com{href}"
        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="Microsoft",
                cidade=cidade,
                link=link,
                fonte="microsoft",
            )
        )
    return vagas


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")

        clicar_se_existir(page, 'button:has-text("Accept")', timeout=4000)

        campo_local = page.get_by_role("combobox", name="City, state, or country/region")
        campo_local.click()
        campo_local.fill(LOCAL_BUSCA)

        opcao = page.get_by_role("option", name=LOCAL_BUSCA, exact=True).first
        opcao.wait_for(state="visible", timeout=10000)
        opcao.click()

        page.locator('[data-testid="search-jobs-button"]').first.click()
        page.wait_for_selector('[class*="cardListItem"]', timeout=20000)
        page.wait_for_timeout(800)

        todas = list(_extrair_pagina(page))

        pagina_atual = 1
        while pagina_atual < MAX_PAGINAS:
            proximo = page.locator('button[aria-label="Next jobs"]').first
            if proximo.count() == 0:
                break
            try:
                if proximo.is_disabled():
                    break
                proximo.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(1200)
            page.wait_for_selector('[class*="cardListItem"]', timeout=15000)
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
