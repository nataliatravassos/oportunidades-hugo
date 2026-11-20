"""
Sonae — portal de oportunidades de carreira (www.sonae.pt).

A Sonae é um grupo com várias marcas (Continente, Worten, Wells, Zu,
Sierra, etc.), então a maioria das vagas é de lojas físicas (vendedor/a,
operador/a de loja...). Ainda assim vale a pena incluir, porque de vez em
quando aparecem vagas de escritório/TI nas "Estruturas" (ex.: "Senior
Software Engineer AI", "Business Analyst & Advisor") — foi assim que
encontramos as duas vagas da Sonae na pesquisa manual que deu origem a
este projeto.

O filtro de localização é por checkbox (não dá pra montar a URL direto):
o scraper clica em "Mostrar mais" pra expandir a lista de distritos e
depois marca o checkbox "Porto". A lista de resultados é paginada com
botões numerados (aria-label="Page N").
"""

from __future__ import annotations

from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, links_dos_cartoes, nova_pagina,
)

URL = "https://www.sonae.pt/pt/talento/oportunidades"
MAX_PAGINAS = 40

SELETOR_CARD = (
    ".border-secondary-200.border-b.bg-white.group.cursor-pointer"
)


def _extrair_pagina(page) -> list[dict]:
    cards = page.locator(SELETOR_CARD)
    total = cards.count()
    vagas = []
    for i in range(total):
        card = cards.nth(i)
        link_el = card.locator("a").first
        if link_el.count() == 0:
            continue
        href = link_el.get_attribute("href")
        paragrafos = card.locator("p")
        n_p = paragrafos.count()
        if n_p < 3 or not href:
            continue
        titulo = paragrafos.nth(0).inner_text().strip()
        categoria = paragrafos.nth(1).inner_text().strip()
        cidade_tipo = paragrafos.nth(2).inner_text().strip()

        # formato observado: "MAIA/CARNAXIDE - Estruturas" ou
        # "V. N. FAMALICÃO - RIBEIRÃO - Lojas"; a última parte depois do
        # último " - " é o tipo de unidade (Estruturas/Lojas/Novas Lojas).
        partes = cidade_tipo.rsplit(" - ", 1)
        cidade = partes[0].strip() if partes else cidade_tipo
        tipo = partes[1].strip() if len(partes) > 1 else None

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="Sonae",
                cidade=cidade,
                link=url_absoluta(href, page.url),
                fonte="sonae",
                categoria=categoria,
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        clicar_se_existir(page, 'button:has-text("Aceitar todos")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Aceitar")', timeout=2000)

        page.wait_for_selector(SELETOR_CARD, timeout=20000)

        # Expande a lista de distritos (só mostra ~10 por padrão) e marca
        # "Porto".
        clicar_se_existir(page, 'text="Mostrar mais"', timeout=3000)
        rotulo_porto = page.locator('label:text-is("Porto")').first
        rotulo_porto.wait_for(state="visible", timeout=10000)
        anteriores = links_dos_cartoes(page, SELETOR_CARD)
        rotulo_porto.click()
        esperar_resultados(page, SELETOR_CARD, anteriores)

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator('button[aria-label="Next page"]').first,
            MAX_PAGINAS,
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
