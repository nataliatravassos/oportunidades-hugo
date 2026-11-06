"""
Funções comuns usadas por todos os módulos de busca (sources/*.py).

Cada módulo de fonte expõe uma função `fetch()` que devolve uma lista de
dicionários no formato produzido por `make_vaga(...)` abaixo. Isso permite
que o `main.py` junte os resultados de todas as fontes num único arquivo,
mesmo que cada site tenha uma estrutura de página completamente diferente.
"""

from __future__ import annotations

import datetime as _dt

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
    cidade: str,
    link: str,
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
