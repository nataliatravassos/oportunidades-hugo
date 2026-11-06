"""Configuração do projeto: região de interesse e lista de fontes ativas."""

# Palavras (em minúsculas, sem acento quando possível) usadas para decidir
# se uma vaga é "da região do Porto". Inclui o distrito do Porto e as
# cidades vizinhas de Aveiro/Braga que ficam a menos de ~1h, porque várias
# empresas (Bosch, Nestlé) só têm fábricas aí perto, não na cidade do Porto.
REGIAO_PORTO = [
    "porto", "matosinhos", "maia", "gaia", "gondomar", "valongo",
    "paços de ferreira", "pacos de ferreira", "santo tirso", "trofa",
    "póvoa de varzim", "povoa de varzim", "vila do conde", "leça", "leca",
    "lousada", "paredes", "penafiel", "felgueiras", "amarante",
    "marco de canaveses", "marco de canavezes",
    "aveiro", "águeda", "agueda", "oliveira de azeméis", "oliveira de azemeis",
    "são joão da madeira", "sao joao da madeira", "espinho", "avanca",
    "braga", "guimarães", "guimaraes",
]


def eh_regiao_porto(cidade: str | None) -> bool:
    if not cidade:
        return False
    c = cidade.lower()
    return any(palavra in c for palavra in REGIAO_PORTO)


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
