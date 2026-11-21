"""Gestão do ciclo de vida das vagas.

Introduz três estados explícitos:
  - observada:     vista na última coleta ou nunca ausentou-se.
  - por_confirmar: ausente em coleta recente, mas sem evidência de encerramento.
  - encerrada:     encerramento comprovado por evidência individual confiável.

Campos novos nos registros:
  - situacao:              "observada" | "por_confirmar" | "encerrada"
  - primeira_observacao:   ISO datetime da primeira coleta conhecida
  - ultima_observacao:     ISO datetime da última vez que apareceu numa coleta
  - ultima_verificacao:    ISO datetime da última tentativa de verificação
  - evidencia_encerramento str | None — motivo confirmado de encerramento

Compatibilidade: registros sem esses campos são migrados on-the-fly (sem
inventar datas históricas — primeira_observacao e ultima_observacao ficam
iguais a coletado_em quando disponível, ou None quando não disponível).
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

SITUACOES_VALIDAS = {"observada", "por_confirmar", "encerrada"}

# Erros que NÃO comprovam encerramento: falha de rede, rate-limit, etc.
ERROS_INCONCLUSIVOS = frozenset({
    "timeout", "connection", "403", "429", "redirect", "ssl",
})


class SituacaoVaga(StrEnum):
    OBSERVADA = "observada"
    POR_CONFIRMAR = "por_confirmar"
    ENCERRADA = "encerrada"


def migrar_vaga(vaga: dict) -> dict:
    """Adiciona campos de ciclo de vida a um registro histórico.

    Nunca inventa datas de observação ou verificação. As datas de primeira
    e última observação podem ser inferidas de coletado_em; ultima_verificacao
    fica nula porque uma coleta não é uma verificação individual.
    verificacao_pendente: True → por_confirmar; False/ausente → observada.
    """
    if "situacao" in vaga:
        return vaga  # já migrado

    pendente = bool(vaga.get("verificacao_pendente"))
    situacao = SituacaoVaga.POR_CONFIRMAR if pendente else SituacaoVaga.OBSERVADA
    coletado = vaga.get("coletado_em")  # pode ser None

    return {
        **vaga,
        "situacao": str(situacao),
        "primeira_observacao": coletado,
        "ultima_observacao": coletado,
        "ultima_verificacao": None,
        "evidencia_encerramento": None,
    }


def inicializar_vaga(vaga: dict) -> dict:
    """Atribui campos de ciclo de vida a uma vaga recém-extraída."""
    agora = vaga.get("coletado_em") or _agora()
    return {
        **vaga,
        "situacao": str(SituacaoVaga.OBSERVADA),
        "primeira_observacao": agora,
        "ultima_observacao": agora,
        "ultima_verificacao": None,
        "evidencia_encerramento": None,
    }


def reapareceu(anterior: dict, nova: dict) -> dict:
    """Reativa uma vaga que voltou a aparecer numa coleta.

    Preserva primeira_observacao e demais dados históricos.
    """
    agora = nova.get("coletado_em") or _agora()
    resultado = {
        **nova,
        "situacao": str(SituacaoVaga.OBSERVADA),
        "primeira_observacao": anterior.get("primeira_observacao") or anterior.get("coletado_em"),
        "ultima_observacao": agora,
        "ultima_verificacao": anterior.get("ultima_verificacao"),
        "evidencia_encerramento": None,
    }
    resultado.pop("verificacao_pendente", None)
    return resultado


def marcar_por_confirmar(vaga: dict, agora: str | None = None) -> dict:
    """Marca que a vaga não foi vista numa coleta, mas sem evidência de encerramento."""
    return {
        **vaga,
        "situacao": str(SituacaoVaga.POR_CONFIRMAR),
        "verificacao_pendente": True,
        # Ausência em coleta não é uma verificação individual.
        "ultima_verificacao": vaga.get("ultima_verificacao"),
        # ultima_observacao NÃO muda — preserva a última vez real
    }


def registrar_verificacao(vaga: dict, *, estado: str, evidencia: str, agora: str | None = None) -> dict:
    """Atualiza o estado depois de uma verificação de disponibilidade individual.

    Estados aceitos: aberta_confirmada, encerrada_confirmada, inconclusiva.
    Só encerrada_confirmada transiciona para encerrada. Inconclusiva não
    confirma disponibilidade nem encerra a vaga.
    """
    ts = agora or _agora()
    base = {**vaga, "ultima_verificacao": ts}
    if estado == "aberta_confirmada":
        return {**base, "situacao": str(SituacaoVaga.OBSERVADA), "verificacao_pendente": False,
                "ultima_observacao": ts, "evidencia_encerramento": None}
    if estado == "inconclusiva":
        return base  # não altera estado
    if estado == "encerrada_confirmada" and _evidencia_encerramento_confiavel(evidencia):
        return {**base, "situacao": str(SituacaoVaga.ENCERRADA),
                "evidencia_encerramento": evidencia, "verificacao_pendente": False}
    return base


def _evidencia_encerramento_confiavel(evidencia: str) -> bool:
    texto = evidencia.lower()
    return "410 gone" in texto or "explicitamente encerrada" in texto


def _agora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
