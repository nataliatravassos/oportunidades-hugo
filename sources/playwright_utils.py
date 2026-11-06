"""Utilitário compartilhado pelos scrapers que precisam de navegador (Playwright).

Vários sites de carreiras (Bosch, FedEx, DHL, IKEA, Siemens, Nestlé,
Microsoft) só mostram as vagas depois de rodar JavaScript (aceitar
cookies, preencher um filtro de localização, etc.), então não dá pra usar
só `requests`. Esses módulos usam o Playwright para abrir um navegador
"headless" (sem interface gráfica) e repetir os mesmos passos que a gente
faria manualmente.
"""

from __future__ import annotations

import contextlib
import logging

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 20_000


@contextlib.contextmanager
def nova_pagina(*, timeout_ms: int = DEFAULT_TIMEOUT_MS):
    """Context manager que devolve uma página Playwright pronta pra uso.

    Uso:
        with nova_pagina() as page:
            page.goto("https://exemplo.com")
            ...
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                locale="pt-PT",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            yield page
        finally:
            browser.close()


def clicar_se_existir(page, selector: str, *, timeout: int = 3000) -> bool:
    """Clica em `selector` se ele aparecer dentro de `timeout` ms.

    Útil pra banners de cookies, que nem sempre aparecem (depende de
    geolocalização / cache), sem travar o scraper quando não aparecem.
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        locator.click()
        return True
    except Exception:  # noqa: BLE001 - não é crítico, só um "melhor esforço"
        return False
