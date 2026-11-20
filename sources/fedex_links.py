"""Rotas de vagas observadas no portal oficial da FedEx."""

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .base import url_absoluta

ORIGEM = "https://careers.fedex.com"
ROTA = re.compile(r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?[\w-]+/job/([a-f0-9]{32})(?:__[a-z]{2}-[a-z]{2})?/?", re.I)


def _rota(caminho: str) -> re.Match[str] | None:
    try:
        partes = [unquote(parte, errors="strict") for parte in caminho.split("/")]
    except UnicodeError:
        return None
    if any("/" in parte for parte in partes):
        return None
    return ROTA.fullmatch("/".join(partes))


def url_vaga_fedex(href: str | None, *, legado: bool = False) -> str | None:
    # O snapshot antigo guardou caminhos a partir da raiz do portal.
    if legado and isinstance(href, str) and href.startswith("/") and not href.startswith("//"):
        if not _rota(urlsplit(href).path):
            return None
        href = url_absoluta(href, ORIGEM)
    url = url_absoluta(href)
    if not url:
        return None
    partes = urlsplit(url)
    if partes.scheme != "https" or partes.netloc.lower() != "careers.fedex.com" or not _rota(partes.path):
        return None
    consulta = "&".join(p for p in partes.query.split("&") if p != "utm_source=CareerSiteOrganic")
    caminho = quote(unquote(partes.path), safe="/")
    return urlunsplit(("https", "careers.fedex.com", caminho, consulta, partes.fragment))


def identidade_fedex(vaga: dict) -> str:
    referencia = vaga.get("categoria") or ""
    if re.fullmatch(r"RC\d+", referencia, re.I):
        return referencia.upper()
    rota = _rota(urlsplit(vaga["link"]).path) if vaga["link"] else None
    return rota[1].upper() if rota else vaga["link_original"]
