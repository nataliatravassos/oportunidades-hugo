"""Configuração do projeto: região de interesse e lista de fontes ativas."""

import re
import unicodedata

# Palavras (em minúsculas, sem acento quando possível) usadas para decidir
# se uma vaga é "da região do Porto". Inclui o distrito do Porto e as
# cidades vizinhas de Aveiro/Braga que ficam a menos de ~1h, porque várias
# empresas (Bosch, Nestlé) só têm fábricas aí perto, não na cidade do Porto.
REGIAO_PORTO = [
    "porto", "matosinhos", "maia", "gaia", "gondomar", "valongo",
    "paços de ferreira", "pacos de ferreira", "santo tirso", "trofa",
    "póvoa de varzim", "povoa de varzim", "vila do conde", "leça", "leca",
    "lousada", "paredes", "penafiel", "felgueiras", "amarante",
    "valbom", "rio tinto", "ermesinde",
    "marco de canaveses", "marco de canavezes",
    "aveiro", "águeda", "agueda", "oliveira de azeméis", "oliveira de azemeis",
    "são joão da madeira", "sao joao da madeira", "espinho", "avanca",
    "braga", "guimarães", "guimaraes",
]


def normalizar_local(texto: str) -> str:
    sem_acentos = "".join(c for c in unicodedata.normalize("NFD", texto.casefold())
                          if not unicodedata.combining(c))
    return " ".join(sem_acentos.split())


_LOCAIS_PORTO = re.compile(r"\b(?:" + "|".join(sorted({re.escape(normalizar_local(p)) for p in REGIAO_PORTO})) + r")\b")
_FORA_REGIAO = re.compile(
    r"\b(?:brasil|brazil|porto alegre|porto seguro|porto velho|porto salvo|porto santo|porto de mos|united states)\b|,\s*us$",
)


def eh_regiao_porto(cidade: str | None) -> bool:
    local = normalizar_local(cidade or "")
    return bool(_LOCAIS_PORTO.search(local) and not _FORA_REGIAO.search(local))


def remoto_elegivel(vaga: dict) -> bool:
    return (vaga.get("modalidade") == "remoto" and vaga.get("remoto_em_portugal") is True
            and bool(vaga.get("evidencia_modalidade")))


# Nome de cada módulo em sources/ que será executado pelo main.py.
# Comente uma linha para desativar temporariamente uma fonte (por exemplo,
# se o site mudou de layout e o scraper está quebrado).
FONTES = [
    "inesctec",
    "fct",
    "sonae",
    "bosch",
    "fedex",
    "dhl",
    "ikea",
    "siemens",
    "nestle",
    "microsoft",
    "outros_institutos",
]
