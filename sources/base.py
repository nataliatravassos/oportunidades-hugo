"""
Funções comuns usadas por todos os módulos de busca (sources/*.py).

Cada módulo de fonte expõe `fetch()` e devolve um ResultadoColeta com
registos no formato produzido por `make_vaga(...)`. Isso permite
que o `main.py` junte os resultados de todas as fontes num único arquivo,
mesmo que cada site tenha uma estrutura de página completamente diferente.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urljoin, urlsplit


class EstadoColeta(StrEnum):
    COMPLETA = "sucesso_completo"
    ZERO = "zero_confirmado"
    PARCIAL = "parcial"
    FALHA = "falha"


@dataclass
class ResultadoColeta:
    estado: EstadoColeta
    vagas: list[dict] = field(default_factory=list)
    motivo: str | None = None
    paginas: int = 0
    consulta: dict = field(default_factory=dict)

    @classmethod
    def avaliar(cls, vagas: list[dict], problemas: list[str], paginas: int = 1, *,
                cobertura: str | None = None, consulta: dict | None = None):
        if not vagas:
            motivo = "; ".join(problemas) or "Nenhuma vaga extraída e zero sem confirmação"
            return cls(EstadoColeta.FALHA, motivo=motivo, paginas=paginas, consulta=consulta or {})
        if not cobertura and not problemas:
            problemas = ["Cobertura integral não demonstrada"]
        if problemas:
            return cls(EstadoColeta.PARCIAL, vagas, "; ".join(problemas), paginas, consulta or {})
        return cls(EstadoColeta.COMPLETA, vagas, motivo=cobertura, paginas=paginas, consulta=consulta or {})


def resumir_erro(erro: Exception) -> str:
    mensagem = str(erro).split("\n", 1)[0]
    return f"{type(erro).__name__}: {mensagem}"[:300]


def url_absoluta(href: str | None, base: str | None = None) -> str | None:
    """Resolve um link de candidatura e rejeita destinos HTTP(S) malformados."""
    if not isinstance(href, str):
        return None
    href = href.strip()
    if (
        not href
        or href.startswith("#")
        or any(c in '\\"<>|' or c.isspace() or ord(c) < 32 or ord(c) == 127 for c in href)
    ):
        return None
    try:
        origem = urlsplit(href)
        if origem.scheme and (origem.scheme not in {"http", "https"} or not origem.netloc):
            return None
        if href.startswith("//") and not origem.netloc:
            return None
        absoluta = urljoin(base, href) if base else href
        destino = urlsplit(absoluta)
        if (
            destino.scheme not in {"http", "https"}
            or not destino.hostname
            or destino.username is not None
            or "%" in destino.hostname
            or destino.netloc.endswith(":")
        ):
            return None
        # A propriedade levanta ValueError para portas inválidas.
        if destino.port == 0:
            return None
    except ValueError:
        return None
    return absoluta

# Palavras que costumam indicar um cargo "operacional": chão de fábrica,
# loja, armazém, cozinha/restauração — ou seja, muito tempo em pé.
# É só uma heurística para ajudar a filtrar rápido; não é 100% confiável,
# então o campo fica no JSON pra você (ou o Hugo) decidir por vaga.
PALAVRAS_OPERACIONAL = [
    "vendedor", "vendedora", "loja", "armazém", "armazem", "caixa",
    "balcão", "balcao", "copa", "cozinha", "restaura", "bistr",
    "operador", "operadora", "manutenção", "manutencao", "eletromecânico",
    "eletromecanico", "técnico de manutenção", "tecnico de manutencao",
    "linha de produção", "linha de producao", "chão de fábrica",
    "motorista", "estafeta", "repositor",
]

PALAVRAS_ESCRITORIO = [
    "analyst", "analista", "engineer", "engenheiro", "engenheira",
    "developer", "desenvolvedor", "scientist", "cientista", "manager",
    "gestor", "specialist", "especialista", "advisor", "consultor",
    "coordinator", "coordenador", "architect", "arquiteto", "researcher",
    "investigador", "data", "software", "it ", "digital",
]


def classificar(titulo: str) -> str:
    """Classificação aproximada por palavra-chave no título do cargo.

    Devolve "operacional" (tende a exigir ficar muito tempo em pé),
    "escritorio" (tende a ser sentado/híbrido) ou "indefinido" quando
    não dá pra saber só pelo título.
    """
    t = titulo.lower()
    if any(p in t for p in PALAVRAS_OPERACIONAL):
        return "operacional"
    if any(p in t for p in PALAVRAS_ESCRITORIO):
        return "escritorio"
    return "indefinido"


def make_vaga(
    *,
    titulo: str,
    empresa: str,
    cidade: str | None,
    link: str | None,
    fonte: str,
    categoria: str | None = None,
    tipo_contrato: str | None = None,
    data_publicacao: str | None = None,
) -> dict:
    """Monta um registro de vaga no formato padrão usado em todo o projeto."""
    titulo = " ".join(titulo.split())
    return {
        "titulo": titulo,
        "empresa": empresa,
        "cidade": cidade.strip() if cidade else None,
        "link": link,
        "fonte": fonte,
        "categoria": categoria,
        "tipo_contrato": tipo_contrato,
        "data_publicacao": data_publicacao,
        "classificacao": classificar(titulo),
        "coletado_em": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
