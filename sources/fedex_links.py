"""Rotas de vagas observadas no portal oficial da FedEx."""

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .base import url_absoluta

ORIGEM = "https://careers.fedex.com"
REQUISICAO = re.compile(r"P\d{2}-\d{6}-\d+", re.I)
ROTA = re.compile(r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?[\w-]+/job/"
                  r"([a-f0-9]{32}|P\d{2}-\d{6}-\d+)(?:__[a-z]{2}-[a-z]{2})?/?", re.I)


def _rota(caminho: str) -> re.Match[str] | None:
    try:
        partes = [unquote(parte, errors="strict") for parte in caminho.split("/")]
    except UnicodeError:
        return None
    if any("/" in parte for parte in partes):
        return None
    return ROTA.fullmatch("/".join(partes))


def url_vaga_fedex(href: str | None, *, legado: bool = False, referencia: str | None = None) -> str | None:
    # O snapshot antigo guardou caminhos a partir da raiz do portal.
    if legado and isinstance(href, str) and href.startswith("/") and not href.startswith("//"):
        if not _rota(urlsplit(href).path):
            return None
        href = url_absoluta(href, ORIGEM)
    url = url_absoluta(href)
    if not url:
        return None
    partes = urlsplit(url)
    rota = _rota(partes.path)
    if partes.scheme != "https" or partes.netloc.lower() != "careers.fedex.com" or not rota:
        return None
    # A variante em texto só é aceita quando coincide com a referência do cartão.
    if REQUISICAO.fullmatch(rota[1]) and rota[1].upper() != (referencia or "").upper():
        return None
    consulta = "&".join(p for p in partes.query.split("&") if p != "utm_source=CareerSiteOrganic")
    caminho = quote(unquote(partes.path), safe="/")
    return urlunsplit(("https", "careers.fedex.com", caminho, consulta, partes.fragment))


def identidade_fedex(vaga: dict) -> str:
    referencia = vaga.get("categoria") or ""
    if re.fullmatch(r"RC\d+", referencia, re.I) or REQUISICAO.fullmatch(referencia):
        return referencia.upper()
    rota = _rota(urlsplit(vaga["link"]).path) if vaga["link"] else None
    return rota[1].upper() if rota else vaga["link_original"]
