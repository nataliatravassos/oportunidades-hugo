"""
DHL — portal de carreiras (careers.dhl.com).

Esse site não aceita um parâmetro de localização direto na URL (testado:
não existe um `?location=Porto` que funcione de forma confiável) — a busca
por local é feita por um campo de autocomplete que sugere localizações
reais (ex.: "Maia, Porto, Portugal") e, ao escolher uma, ativa uma busca
por raio (perímetro) de 100 km ao redor dela. O scraper reproduz esse
fluxo: digita "Porto" no campo de localização, espera a sugestão
"Maia, Porto, Portugal" aparecer e clica nela, depois clica em "Find Jobs".

Essa busca por perímetro também traz vagas fora da região (ex.: Lisboa),
então — assim como em bosch.py — a filtragem final por região fica a
cargo do main.py, usando o campo "cidade" de cada vaga.

A lista de resultados é paginada (10 por página) com links numerados,
igual ao fedex.py.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlsplit

from config import eh_regiao_porto, normalizar_local
from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, links_dos_cartoes, nova_pagina,
)

logger = logging.getLogger(__name__)

URL = "https://careers.dhl.com/global/en/search-results"
LOCAL_BUSCA = "Porto"
MAX_PAGINAS = 10
SELETOR_CARD = "li.jobs-list-item"


def local_dhl_valido(local: str) -> bool:
    return eh_regiao_porto(local) and bool(re.search(r"\b(?:portugal|pt)\b", normalizar_local(local)))


def filtro_confirmado(url: str, escolhido: str, campo: str) -> bool:
    if not local_dhl_valido(escolhido):
        return False
    if normalizar_local(campo) == normalizar_local(escolhido):
        return True
    parametros = parse_qs(urlsplit(url).query)
    return bool(parametros.get("p")) and any(
        normalizar_local(local) == normalizar_local(escolhido)
        for local in parametros.get("location", [])
    )


def _extrair_pagina(page) -> list[dict]:
    itens = page.locator(SELETOR_CARD)
    total = itens.count()
    vagas = []
    for i in range(total):
        item = itens.nth(i)
        link_el = item.locator("a").first
        if link_el.count() == 0:
            continue
        href = link_el.get_attribute("href")
        titulo_el = item.locator(".job-title").first
        titulo = titulo_el.inner_text().strip() if titulo_el.count() else None
        if not titulo or not href:
            continue

        loc_el = item.locator(".job-location").first
        cidade = None
        if loc_el.count():
            cidade = re.sub(r"^\s*Location\s*", "", loc_el.inner_text().strip()).strip()

        info_el = item.locator(".job-info").first
        tipo = None
        if info_el.count():
            info_texto = re.sub(r"\s+", " ", info_el.inner_text()).strip()
            tipo = info_texto.replace("Location", "").replace(cidade or "", "").strip() or None

        vagas.append(
            make_vaga(
                titulo=titulo,
                empresa="DHL",
                cidade=cidade,
                link=url_absoluta(href, page.url),
                fonte="dhl",
                tipo_contrato=tipo,
            )
        )
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        # Banner de cookies: melhor esforço, nem sempre aparece.
        clicar_se_existir(page, 'button:has-text("Accept All")', timeout=4000)

        campo_local = page.locator("#gllocationInput")
        campo_local.fill("")
        campo_local.press_sequentially(LOCAL_BUSCA, delay=75)
        lista = campo_local.get_attribute("aria-controls")
        if not lista:
            raise ValueError("O campo de localização não aponta para uma lista de sugestões")
        opcoes = page.locator(f'[id="{lista}"]').locator('[role="option"]:visible, a:visible')
        # Só escolha sugestões do próprio autocomplete que identifiquem Portugal.
        tem_pais = opcoes.filter(has_text=re.compile(r"\b(?:Portugal|PT)\b", re.I)).first
        tem_pais.wait_for(timeout=10000)
        sugestao = next((opcao for opcao in opcoes.all() if local_dhl_valido(opcao.inner_text())), None)
        if sugestao is None:
            raise ValueError("Autocomplete da DHL sem uma localização confirmada na região do Porto")
        local_selecionado = sugestao.inner_text()
        sugestao.click()

        anteriores = links_dos_cartoes(page, SELETOR_CARD)
        page.get_by_role("button", name=re.compile(r"^Find Jobs$", re.I)).last.click()
        esperar_resultados(page, SELETOR_CARD, anteriores)
        if not filtro_confirmado(page.url, local_selecionado, campo_local.input_value()):
            raise ValueError("A localização selecionada não foi mantida após a pesquisa DHL")

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator(f'a.phw-s-page-number-link:text-is("{numero + 1}")').first,
            MAX_PAGINAS,
            consulta={"url": page.url, "escopo": "Busca por perímetro; localização validada após o envio",
                      "local_selecionado": local_selecionado},
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
