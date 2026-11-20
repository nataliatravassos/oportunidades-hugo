"""Bosch Careers em Portugal, com expansão da lista e filtro regional local."""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .base import ResultadoColeta, make_vaga, resumir_erro, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, esperar_resultados, links_dos_cartoes, nova_pagina,
)

URL = "https://jobs.bosch.com/en/?pages=1&country=pt"
MAX_CLIQUES_CARREGAR_MAIS = 30
SELETOR_CARD = ".M-JobSearchResultsGroup__item"

def _data_publicacao(valor: str | None) -> str | None:
    for formato in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor or "", formato).date().isoformat()
        except ValueError:
            continue
    return None


def extrair_cartao(html: str, url: str) -> dict | None:
    cartao = BeautifulSoup(html, "html.parser")
    cabecalho = cartao.select_one("a.A-JobPanel__header[href]")
    titulo = cartao.select_one(".A-JobPanel__title")
    if not cabecalho or not titulo:
        return None

    def texto(seletor):
        elemento = cartao.select_one(seletor)
        return elemento.get_text(" ", strip=True) if elemento else None

    cidade = texto('.A-JobPanel__description:has(i[title="locator"]) .A-JobPanel__value')
    categoria = texto('.A-JobPanel__description:has(i[title="briefcase"]) .A-JobPanel__value')
    data = texto('.A-JobPanel__description:has(i[title="calendar"]) .A-JobPanel__value')
    modo = texto(".A-JobPanel__remote")
    link = url_absoluta(cabecalho["href"], url)
    destino = urlsplit(link or "")
    if (not cidade or destino.scheme != "https" or destino.netloc != "jobs.bosch.com"
            or not re.fullmatch(r"/en/job/REF\d+[A-Za-z]?-([^/]+)/?", destino.path)):
        return None
    vaga = make_vaga(
        titulo=titulo.get_text(" ", strip=True), empresa="Bosch", cidade=cidade,
        link=link, fonte="bosch", categoria=categoria, data_publicacao=_data_publicacao(data),
    )
    if modo:
        vaga["modalidade"] = {"hybrid": "hibrido", "on-site": "presencial", "remote": "remoto"}.get(modo.casefold(), "desconhecido")
        vaga["evidencia_modalidade"] = modo
    return vaga


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        # O banner de cookies nem sempre aparece (depende de cache), então
        # isso é "melhor esforço": se não aparecer em 4s, segue em frente.
        clicar_se_existir(page, 'button:has-text("Decline all")', timeout=4000)

        esperar_resultados(page, SELETOR_CARD, [])

        problemas = []
        vagas = {}
        paginas = 0
        vistos = set()
        botao = page.locator('button:has-text("See all jobs")').first
        for cliques in range(MAX_CLIQUES_CARREGAR_MAIS + 1):
            try:
                links = links_dos_cartoes(page, SELETOR_CARD)
                vistos.update(filter(None, links))
                extraidas = _extrair_pagina(page)
                paginas += 1
                for vaga in extraidas:
                    vagas.setdefault(vaga["link"] or vaga["titulo"], vaga)
                if len(extraidas) != len(links):
                    problemas.append(f"{len(extraidas)}/{len(links)} cartões extraídos")
                if botao.count() == 0 or not botao.is_visible() or botao.is_disabled():
                    break
                if cliques == MAX_CLIQUES_CARREGAR_MAIS:
                    problemas.append("Limite de carregamentos atingido com navegação restante")
                    break
                botao.click()
                esperar_resultados(page, SELETOR_CARD, links, crescer=True)
            except Exception as erro:
                problemas.append(f"Carregar mais: {resumir_erro(erro)}")
                break
        resumo = page.get_by_text(re.compile(r"Your results:\s*\d+ results?", re.I)).first
        contador = next(iter(resumo.all_text_contents()), "")
        total = re.search(r"(\d+)\s+results?", contador, re.I)
        consulta = {"url": page.url, "escopo": "Busca Portugal; expansão pelo botão See all jobs",
                    "cartoes_distintos": len(vistos), "total_anunciado": int(total[1]) if total else None}
        return ResultadoColeta.avaliar(list(vagas.values()), problemas, paginas, consulta=consulta)


def _extrair_pagina(page) -> list[dict]:
    return [vaga for card in page.locator(SELETOR_CARD).all()
            if (vaga := extrair_cartao(card.inner_html(), page.url)) is not None]


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
