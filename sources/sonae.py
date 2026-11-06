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

from .base import make_vaga
from .playwright_utils import clicar_se_existir, nova_pagina

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
                link=href if href.startswith("http") else f"https://www.sonae.pt{href}",
                fonte="sonae",
                categoria=categoria,
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> list[dict]:
    with nova_pagina() as page:
        page.goto(URL, wait_until="domcontentloaded")

        clicar_se_existir(page, 'button:has-text("Aceitar todos")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Aceitar")', timeout=2000)

        page.wait_for_selector(SELETOR_CARD, timeout=20000)

        # Expande a lista de distritos (só mostra ~10 por padrão) e marca
        # "Porto".
        clicar_se_existir(page, 'text="Mostrar mais"', timeout=3000)
        rotulo_porto = page.locator('label:text-is("Porto")').first
        rotulo_porto.wait_for(state="visible", timeout=10000)
        rotulo_porto.click()

        # Espera a lista recarregar (o texto do contador "Todas N" muda).
        page.wait_for_timeout(1500)
        page.wait_for_selector(SELETOR_CARD, timeout=20000)

        todas = list(_extrair_pagina(page))

        pagina_atual = 1
        while pagina_atual < MAX_PAGINAS:
            proximo = page.locator('button[aria-label="Next page"]').first
            if proximo.count() == 0:
                break
            try:
                desabilitado = proximo.get_attribute("disabled") is not None or proximo.is_disabled()
            except Exception:  # noqa: BLE001
                desabilitado = False
            if desabilitado:
                break
            try:
                proximo.click()
            except Exception:  # noqa: BLE001
                break
            page.wait_for_timeout(1200)
            page.wait_for_selector(SELETOR_CARD, timeout=15000)
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
