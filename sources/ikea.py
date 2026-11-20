"""
IKEA — portal de carreiras (jobs.ikea.com), construído sobre a plataforma
Phenom People.

Esse site não aceita um nome de cidade solto na URL: a busca por
localização usa autocomplete (sugestões tipo "Porto, Porto" vs.
"Porto Alegre, Rio Grande do Sul") e, ao escolher uma sugestão, monta uma
URL com as coordenadas geográficas (latitude/longitude) e um raio de
busca em km. Fizemos essa busca manualmente uma vez (digitando "Porto",
escolhendo a sugestão portuguesa "Porto, Porto" e clicando em "Search
jobs") e a URL resultante abaixo é estável — reabri-la direto, sem
repetir os cliques, devolve a mesma lista de vagas. Por isso aqui a gente
só navega pra essa URL pronta em vez de reproduzir o fluxo de
autocomplete (mais simples e mais robusto do que depender do dropdown).

No momento em que isso foi testado, a busca devolvia só 7 vagas (cabem
todas numa página só, sem paginação visível). Se um dia a Localização
tiver muito mais vagas, pode ser necessário investigar paginação de novo.
"""

from __future__ import annotations

import re

from .base import ResultadoColeta, make_vaga, url_absoluta
from .playwright_utils import abrir_busca, clicar_se_existir, nova_pagina

URL = (
    "https://jobs.ikea.com/en/search-jobs/Porto/22908/4/"
    "2264397-2735941-6458924-8012861-2735943/41x14961/-8x61099/25/2"
)


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)

        clicar_se_existir(page, 'button:has-text("Accept")', timeout=4000)
        clicar_se_existir(page, 'button:has-text("Aceitar")', timeout=2000)

        page.wait_for_selector("li.job-list__item", timeout=20000)

        itens = page.locator("li.job-list__item")
        total = itens.count()
        vagas = []
        for i in range(total):
            item = itens.nth(i)
            a = item.locator("a.job-list__anchor").first
            if a.count() == 0:
                continue
            href = a.get_attribute("href")
            titulo_el = item.locator(".job-list__title").first
            titulo = titulo_el.inner_text().strip() if titulo_el.count() else None
            if not titulo or not href:
                continue

            cidade_el = item.locator(".job-list__location").first
            cidade = cidade_el.inner_text().strip() if cidade_el.count() else None

            cat_el = item.locator(".job-list__categories").first
            categoria = cat_el.inner_text().strip() if cat_el.count() else None

            tipo_el = item.locator(".job-list__job-type").first
            tipo = tipo_el.inner_text().strip() if tipo_el.count() else None

            vagas.append(
                make_vaga(
                    titulo=titulo,
                    empresa="IKEA",
                    cidade=cidade,
                    link=url_absoluta(href, page.url),
                    fonte="ikea",
                    categoria=categoria,
                    tipo_contrato=tipo,
                )
            )
        problemas = []
        if len(vagas) != total:
            problemas.append(f"{len(vagas)}/{total} cartões extraídos")
        paginacao = page.locator('[rel="next"], .pagination a, .pagination button')
        if paginacao.count():
            problemas.append("Controles de paginação presentes; apenas a primeira página foi lida")
        resumo = page.get_by_text(re.compile(r"^\s*\d+ results? for Porto\s*$", re.I)).all_text_contents()
        total_anunciado = next((int(s.split()[0]) for s in resumo), None)
        cobertura = None
        if total_anunciado == total == len({vaga["link"] for vaga in vagas}) and not problemas:
            cobertura = "Todos os resultados anunciados para a busca de Porto foram lidos"
        return ResultadoColeta.avaliar(vagas, problemas, cobertura=cobertura, consulta={
            "url": page.url, "escopo": "Busca Porto, raio publicado de 25 km",
            "cartoes_lidos": total, "total_anunciado": total_anunciado,
        })


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
