"""Pesquisa Portugal no portal Microsoft e confirma o regime no anúncio."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from config import normalizar_local
from .base import ResultadoColeta, make_vaga, resumir_erro, url_absoluta
from .playwright_utils import (
    abrir_busca, clicar_se_existir, coletar_paginas, esperar_resultados, links_dos_cartoes, nova_pagina,
)

URL = "https://jobs.careers.microsoft.com/global/en/search"
LOCAL_BUSCA = "Portugal"
MAX_PAGINAS = 10
MAX_DETALHES = 12
SELETOR_CARD = '[role="listitem"]:has([data-test-id="job-listing"])'


def em_portugal(local: str | None) -> bool:
    return any(normalizar_local(parte) == "portugal" for parte in (local or "").split(","))


def extrair_cartao(html: str, base: str) -> dict | None:
    card = BeautifulSoup(html, "html.parser")
    anuncio = card.select_one('a[href*="/careers/job/"]')
    titulo = card.select_one('[class*="title-"]')
    cidade = card.select_one('[class*="fieldValue-"]')
    if not anuncio or not titulo or not cidade:
        return None
    link = url_absoluta(anuncio["href"], base)
    if not link or not _anuncio_oficial(link):
        return None
    return {
        **make_vaga(titulo=titulo.get_text(" ", strip=True), empresa="Microsoft",
                    cidade=cidade.get_text(" ", strip=True), link=link, fonte="microsoft"),
        "modalidade": "desconhecido",
    }


def _anuncio_oficial(link: str) -> bool:
    partes = urlsplit(link)
    return (partes.scheme == "https" and partes.netloc == "apply.careers.microsoft.com"
            and bool(re.fullmatch(r"/careers/job/\d+/?", partes.path)))


def _extrair_pagina(page) -> list[dict]:
    return [vaga for card in page.locator(SELETOR_CARD).all()
            if (vaga := extrair_cartao(card.inner_html(), page.url)) is not None]


def modalidade_do_anuncio(html: str, local: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    valores = []
    for termo in soup.select("dl dt"):
        if normalizar_local(termo.get_text(" ", strip=True)) == "work site":
            valor = termo.find_next_sibling("dd")
            if valor:
                valores.append(valor.get_text(" ", strip=True))
    if len(set(valores)) != 1:
        return {"modalidade": "desconhecido"}
    evidencia = valores[0]
    normal = normalizar_local(evidencia).replace("–", "-").replace("—", "-")
    dias = re.fullmatch(r"([0-5]) days?\s*/\s*week in-office(?:\s*-\s*remote)?", normal)
    modalidade = "desconhecido"
    if dias:
        if dias[1] == "0":
            modalidade = "remoto" if normal.endswith("remote") else "desconhecido"
        else:
            modalidade = "presencial" if dias[1] == "5" else "hibrido"
    elif normal in {"fully on-site", "fully on site"}:
        modalidade = "presencial"
    return {
        "modalidade": modalidade, "evidencia_modalidade": evidencia,
        "remoto_em_portugal": modalidade == "remoto" and em_portugal(local),
    }


def _consultar_modalidades(page, resultado: ResultadoColeta) -> None:
    candidatas = [vaga for vaga in resultado.vagas if em_portugal(vaga["cidade"])]
    consulta = resultado.consulta
    consulta.update({"anuncios_com_portugal_visivel": len(candidatas), "limite_detalhes": MAX_DETALHES,
                     "detalhes_consultados": 0, "detalhes_sem_modalidade": 0,
                     "localizacoes_adicionais": "Países que não aparecem no cartão não são inferidos"})
    if not candidatas:
        return
    detalhe = page.context.new_page()
    try:
        for vaga in candidatas[:MAX_DETALHES]:
            consulta["detalhes_consultados"] += 1
            try:
                resposta = detalhe.goto(vaga["link"], wait_until="domcontentloaded", timeout=12000)
                if not resposta or not resposta.ok or not _anuncio_oficial(detalhe.url):
                    raise ValueError("Página de detalhe indisponível ou redirecionada")
                termo = detalhe.locator("dl dt").filter(has_text=re.compile(r"^Work site$", re.I)).first
                termo.wait_for(timeout=5000)
                vaga.update(modalidade_do_anuncio(detalhe.content(), vaga["cidade"]))
            except Exception as erro:
                consulta["ultimo_erro_detalhe"] = resumir_erro(erro)
            if vaga["modalidade"] == "desconhecido":
                consulta["detalhes_sem_modalidade"] += 1
    finally:
        detalhe.close()


def fetch() -> ResultadoColeta:
    with nova_pagina() as page:
        abrir_busca(page, URL)
        clicar_se_existir(page, 'button:has-text("Reject")', timeout=2500)
        campo = page.get_by_role("combobox", name="City, state, or country/region")
        campo.fill(LOCAL_BUSCA)
        page.get_by_role("option", name=LOCAL_BUSCA, exact=True).first.click()
        anteriores = links_dos_cartoes(page, SELETOR_CARD)
        page.locator('[data-testid="search-jobs-button"]').first.click()
        esperar_resultados(page, SELETOR_CARD, anteriores)
        if normalizar_local(campo.input_value()) != "portugal":
            raise ValueError("O campo de localização não ficou em Portugal")
        resultado = coletar_paginas(
            page, SELETOR_CARD, _extrair_pagina,
            lambda numero: page.locator('button[aria-label="Next jobs"]').first, MAX_PAGINAS,
            consulta={"url": page.url, "escopo": "Busca Portugal confirmada no campo de localização"},
        )
        _consultar_modalidades(page, resultado)
        return resultado


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
