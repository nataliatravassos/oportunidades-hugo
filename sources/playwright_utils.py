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

from .base import ResultadoColeta, resumir_erro

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


class ErroNavegacao(RuntimeError):
    def __init__(self, status: int | None):
        self.status = status
        super().__init__(f"Navegação para a busca: HTTP {status if status is not None else 'sem resposta'}")


def abrir_busca(page, url: str) -> None:
    resposta = page.goto(url, wait_until="domcontentloaded")
    if resposta is None or not resposta.ok:
        raise ErroNavegacao(resposta.status if resposta is not None else None)


LINKS_DOS_CARTOES = """cards => cards.map(card =>
    card.querySelector('a[href]')?.getAttribute('href') ?? ''
)"""


def links_dos_cartoes(page, seletor: str) -> list[str]:
    return page.locator(seletor).evaluate_all(LINKS_DOS_CARTOES)


def esperar_resultados(page, seletor: str, anteriores: list[str], *, crescer: bool = False) -> None:
    page.wait_for_function(
        """({seletor, anteriores, crescer}) => {
            const links = Array.from(document.querySelectorAll(seletor), card =>
                card.querySelector('a[href]')?.getAttribute('href') ?? ''
            );
            return links.some(Boolean) && (crescer
                ? links.length > anteriores.length
                : JSON.stringify([...new Set(links)].sort()) !==
                  JSON.stringify([...new Set(anteriores)].sort()));
        }""",
        arg={"seletor": seletor, "anteriores": anteriores, "crescer": crescer},
        timeout=15000,
    )


def coletar_paginas(page, seletor: str, extrair, proxima, limite: int, *,
                   consulta: dict | None = None) -> ResultadoColeta:
    """Conserva os resultados já lidos caso uma página deixe de avançar."""
    vagas = {}
    problemas = []
    assinaturas = set()
    paginas = 0
    cartoes_lidos = 0
    cartoes_processados = 0
    cartoes_invalidos = 0
    for numero in range(1, limite + 1):
        try:
            links = links_dos_cartoes(page, seletor)
            assinatura = frozenset(links)
            if assinatura in assinaturas:
                problemas.append(f"Página {numero} repetida")
                break
            assinaturas.add(assinatura)
            cartoes_lidos += len(links)
            extraidas = extrair(page)
            cartoes_processados += len(links)
            cartoes_invalidos += max(0, len(links) - len(extraidas))
            paginas += 1
            for vaga in extraidas:
                # Mantenha também os links inválidos para a validação central.
                chave = vaga["link"] or (numero, len(vagas))
                vagas.setdefault(chave, vaga)
            if len(extraidas) != len(links):
                problemas.append(f"Página {numero}: {len(extraidas)}/{len(links)} cartões extraídos")

            controle = proxima(numero)
            if controle.count() == 0 or controle.is_disabled():
                break
            if numero == limite:
                problemas.append(f"Limite de {limite} páginas atingido com navegação restante")
                break
            controle.click()
            esperar_resultados(page, seletor, links)
        except Exception as erro:
            problemas.append(f"Paginação a partir da página {numero}: {resumir_erro(erro)}")
            break
    diagnostico = {
        **(consulta or {}),
        "limite_paginas": limite,
        "cartoes_lidos": cartoes_lidos,
        "cartoes_invalidos": cartoes_invalidos,
        "cartoes_sem_processar": cartoes_lidos - cartoes_processados,
    }
    return ResultadoColeta.avaliar(list(vagas.values()), problemas, paginas, consulta=diagnostico)
