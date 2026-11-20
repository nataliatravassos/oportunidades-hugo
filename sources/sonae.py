"""Sonae, limitada aos destinos explícitos no HTML público da listagem."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import requests
from bs4 import BeautifulSoup

from config import normalizar_local
from .base import ResultadoColeta, make_vaga, url_absoluta

URL = "https://www.sonae.pt/pt/talento/oportunidades"
SELETOR_CARD = 'div[role="button"].border-secondary-200.border-b:has(p)'
ROTA = re.compile(r"/pt/talento/oportunidades/(?:([^/]+)-)?([1-9][0-9]{0,11})/?")


def _extrair_cartao(cartao, base: str) -> dict | None:
    linhas = [p.get_text(" ", strip=True) for p in cartao.select("p")]
    if len(linhas) < 3 or any(not s for s in linhas[:3]):
        return None
    titulo, categoria, cidade_tipo = linhas[:3]
    titulo_slug = "-".join(re.findall(r"[a-z0-9]+", normalizar_local(titulo)))
    destinos = {}
    for a in cartao.select("a[href]"):
        link = url_absoluta(a["href"], base)
        if not link:
            continue
        local = urlsplit(link)
        rota = ROTA.fullmatch(unquote(local.path))
        if local.scheme != "https" or local.netloc != "www.sonae.pt" or not rota:
            continue
        if rota[1] and rota[1].casefold() != titulo_slug:
            return None
        destinos[rota[2]] = link
    if len(destinos) != 1:
        return None
    partes = cidade_tipo.rsplit(" - ", 1)
    return make_vaga(
        titulo=titulo, empresa="Sonae", cidade=partes[0], link=next(iter(destinos.values())),
        fonte="sonae", categoria=categoria, tipo_contrato=partes[1] if len(partes) > 1 else None,
    )


def extrair_listagem(html: str, base: str) -> ResultadoColeta:
    cartoes = BeautifulSoup(html, "html.parser").select(SELETOR_CARD)
    por_id = {}
    conflitos = set()
    invalidos = 0
    for cartao in cartoes:
        vaga = _extrair_cartao(cartao, base)
        if not vaga:
            invalidos += 1
            continue
        rota = ROTA.fullmatch(unquote(urlsplit(vaga["link"]).path))
        identificador = rota[2]
        anterior = por_id.setdefault(identificador, vaga)
        if any(anterior[campo] != vaga[campo] for campo in ("titulo", "cidade", "tipo_contrato")):
            conflitos.add(identificador)
    vagas = [vaga for identificador, vaga in por_id.items() if identificador not in conflitos]
    problemas = []
    if invalidos:
        problemas.append(f"{invalidos} cartão(ões) sem destino explícito e inequívoco")
    if conflitos:
        problemas.append(f"{len(conflitos)} destino(s) com dados divergentes em cartões diferentes")
    if not vagas:
        problemas.append("A listagem pública não apresentou anúncios com ligação; a API está excluída pelo robots.txt")
    return ResultadoColeta.avaliar(vagas, problemas, consulta={
        "url": base, "escopo": "Apenas HTML inicial da listagem; filtro e páginas dinâmicas não consultados",
        "cartoes_lidos": len(cartoes),
    })


def fetch() -> ResultadoColeta:
    resposta = requests.get(URL, timeout=15)
    resposta.raise_for_status()
    if resposta.url.rstrip("/") != URL:
        raise ValueError("A listagem Sonae redirecionou para um endereço inesperado")
    return extrair_listagem(resposta.text, resposta.url)


if __name__ == "__main__":
    import json
    from dataclasses import asdict

    print(json.dumps(asdict(fetch()), indent=2, ensure_ascii=False))
