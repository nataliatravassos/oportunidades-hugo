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

import re
from urllib.parse import unquote, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout, expect

from config import normalizar_local
from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, nova_pagina, texto_dos_cartoes,
)

URL = "https://www.sonae.pt/pt/talento/oportunidades"
MAX_PAGINAS = 40

SELETOR_CARD = (
    'div[role="button"].border-secondary-200.border-b:has(p)'
)
ROTAS_ANUNCIO = "**/pt/talento/oportunidades/**"


def _link_anuncio(href: str | None, base: str) -> str | None:
    url = url_absoluta(href, base)
    if url:
        partes = urlsplit(url)
        if (partes.scheme == "https" and partes.netloc == "www.sonae.pt"
                and re.fullmatch(r"/pt/talento/oportunidades/[^/]+-\d+/?", partes.path)):
            return url
    return None


def _titulo_corresponde(titulo: str, link: str) -> bool:
    slug = unquote(urlsplit(link).path.rstrip("/").rsplit("/", 1)[-1])
    titulo_slug = "-".join(re.findall(r"[a-z0-9]+", normalizar_local(titulo)))
    return bool(titulo_slug) and slug.casefold().startswith(titulo_slug + "-")


def _extrair_pagina(page) -> list[dict]:
    # Os cartões atuais navegam na própria aba sem <a>. Leia o destino real
    # do clique, resolvendo localmente a navegação com 204. O anúncio nunca
    # é requisitado ao portal e a aba permanece na listagem.
    def suprimir_destino(rota):
        if rota.request.is_navigation_request():
            rota.fulfill(status=204)
        else:
            rota.continue_()

    vagas = []
    page.route(ROTAS_ANUNCIO, suprimir_destino)
    try:
        for card in page.locator(SELETOR_CARD).all():
            linhas = card.locator("p").all_inner_texts()
            if len(linhas) < 3:
                continue
            a = card.locator("a[href]").first
            href = a.get_attribute("href") if a.count() else None
            if not href:
                try:
                    with page.expect_request(lambda r: r.is_navigation_request() and bool(_link_anuncio(r.url, page.url)),
                                             timeout=2000) as destino:
                        card.click(timeout=2500)
                    href = destino.value.url
                except PlaywrightTimeout:
                    continue
            titulo, categoria, cidade_tipo = linhas[:3]
            link = _link_anuncio(href, page.url)
            if not link or not _titulo_corresponde(titulo, link):
                continue
            partes = cidade_tipo.rsplit(" - ", 1)
            vagas.append(make_vaga(titulo=titulo, empresa="Sonae", cidade=partes[0].strip(), link=link,
                                  fonte="sonae", categoria=categoria,
                                  tipo_contrato=partes[1].strip() if len(partes) > 1 else None))
    finally:
        page.unroute(ROTAS_ANUNCIO, suprimir_destino)
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        clicar_se_existir(page, 'button:has-text("Utilizar só os cookies necessários")', timeout=3500)

        page.wait_for_selector(SELETOR_CARD, timeout=20000)

        rotulo = page.locator('label[for^="location-"]').filter(has_text=re.compile(r"^\s*Porto\s*(?:\(\d+\))?\s*$", re.I))
        if not rotulo.count():
            page.get_by_role("button", name=re.compile(r"^Mostrar mais\b", re.I)).first.click()
        identificador = rotulo.get_attribute("for")
        checkbox = page.locator(f'[role="checkbox"][id="{identificador}"]')
        anteriores = texto_dos_cartoes(page, SELETOR_CARD)
        if checkbox.get_attribute("aria-checked") != "true":
            checkbox.click()
            expect(checkbox).to_have_attribute("aria-checked", "true")
            esperar_resultados(page, SELETOR_CARD, anteriores, usar_texto=True)
        else:
            expect(checkbox).to_have_attribute("aria-checked", "true")

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator('button[aria-label="Next page"]').first,
            MAX_PAGINAS,
            consulta={"url": page.url, "escopo": "Distrito Porto confirmado no checkbox de localização"},
            usar_texto=True,
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
