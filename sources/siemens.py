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

import re
import json
from urllib.parse import parse_qs, urlsplit

from config import normalizar_local
from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, links_dos_cartoes, nova_pagina,
)

URL = "https://jobs.siemens.com/pt_PT/externaljobs"
MAX_PAGINAS = 20
SELETOR_CARD = "article.article--result"


def _selecionar(page, filtro: str, valor: str) -> tuple[str, str]:
    select = page.locator(f"select.search_param--{filtro}").first
    if filtro == "country":
        identificador = select.get_attribute("id")
        campo = page.locator(f'input[role="searchbox"][aria-labelledby="{identificador}-label"]:visible')
        campo.click()
        campo.press_sequentially(valor, delay=55)
        opcao = page.locator('li.select2-results__option[role="option"]:visible').filter(
            has_text=re.compile(rf"^\s*{re.escape(valor)}\s*$", re.I),
        )
        opcao.click()
        page.keyboard.press("Escape")
    else:
        # O Select2 popula o select dependente depois da escolha de país.
        # Escolher a opção nativa dispara o mesmo evento change do formulário.
        select.select_option(label=valor, force=True)
    selecionada = select.locator("option:checked")
    if selecionada.count() != 1 or normalizar_local(selecionada.inner_text()) != normalizar_local(valor):
        raise ValueError(f"Filtro Siemens não confirmado: {filtro}")
    return select.get_attribute("name"), selecionada.get_attribute("value")


def _filtros_aplicados(page, filtros: list[tuple[str, str]]) -> bool:
    parametros = parse_qs(urlsplit(page.url).query)

    def valores_url(nome):
        for campo in (nome, nome.removesuffix("[]")):
            for valor in parametros.get(campo, []):
                if valor.startswith("["):
                    try:
                        itens = json.loads(valor)
                    except ValueError:
                        continue
                    if isinstance(itens, list):
                        yield from map(str, itens)
                else:
                    yield valor

    return all(
        valor in valores_url(nome) or
        valor in page.locator(f'select[name="{nome}"] option:checked').evaluate_all("(opcoes) => opcoes.map(o => o.value)")
        for nome, valor in filtros
    )


def _extrair_pagina(page) -> list[dict]:
    cards = page.locator(SELETOR_CARD)
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
                link=url_absoluta(href, page.url),
                fonte="siemens",
                categoria=categoria or jobid,
            )
        )
    return vagas


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        clicar_se_existir(page, 'button:has-text("Accept")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Aceitar")', timeout=2000)

        filtros = [_selecionar(page, "country", "Portugal")]
        distritos = page.locator("select.search_param--state option").all_text_contents()
        if any(normalizar_local(distrito) == "porto" for distrito in distritos):
            filtros.append(_selecionar(page, "state", "Porto"))

        anteriores = links_dos_cartoes(page, SELETOR_CARD)
        page.get_by_role("button", name=re.compile(r"^Pesquisar$", re.I)).first.click()
        esperar_resultados(page, SELETOR_CARD, anteriores)
        if not _filtros_aplicados(page, filtros):
            raise ValueError("Filtros selecionados não confirmados nos resultados Siemens")
        escopo = ("Portugal e distrito Porto confirmados após o envio" if len(filtros) == 2
                  else "Portugal confirmado; distrito não disponível no formulário inicial, recorte regional aplicado aos cartões")

        return coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator(".list-controls__pagination__item.paginationNextLink a").first,
            MAX_PAGINAS,
            consulta={"url": page.url, "escopo": escopo},
        )


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
