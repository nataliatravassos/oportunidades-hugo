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

from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, links_dos_cartoes, nova_pagina,
)

URL = "https://jobs.careers.microsoft.com/global/en/search"
LOCAL_BUSCA = "Portugal"
MAX_PAGINAS = 10
SELETOR_CARD = '[class*="cardListItem"]'


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
        texto = card.inner_text().strip()
        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        if len(linhas) < 2 or not href:
            continue
        titulo = linhas[0]
        cidade = linhas[1]

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="Microsoft",
                cidade=cidade,
                link=url_absoluta(href, page.url),
                fonte="microsoft",
            )
        )
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        clicar_se_existir(page, 'button:has-text("Accept")', timeout=4000)

        campo_local = page.get_by_role("combobox", name="City, state, or country/region")
        campo_local.click()
        campo_local.fill(LOCAL_BUSCA)

        opcao = page.get_by_role("option", name=LOCAL_BUSCA, exact=True).first
        opcao.wait_for(state="visible", timeout=10000)
        opcao.click()

        anteriores = links_dos_cartoes(page, SELETOR_CARD)
        page.locator('[data-testid="search-jobs-button"]').first.click()
        esperar_resultados(page, SELETOR_CARD, anteriores)

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator('button[aria-label="Next jobs"]').first,
            MAX_PAGINAS,
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
