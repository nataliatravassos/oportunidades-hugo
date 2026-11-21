"""Verificação de disponibilidade individual de vagas.

Principios:
  - Não-destrutivo: nunca encerra uma vaga com base em falha de rede,
    timeout, HTTP 403/429, ou ausência em coleta parcial.
  - Encerramento só com evidência individual confiável:
    * HTTP 410 Gone (vaga explicitamente removida)
    * HTTP 404 de URLs específicas de vagas (não de páginas de busca)
    * Resposta do site indicando "vaga não existe / encerrada"
  - Respeitoso: taxa máxima de 1 req/s por domínio, sem parallelismo.
  - Limitado: configurável, desativado por padrão em CI.

Uso típico (apenas para vagas por_confirmar há N dias):
    verificador = VerificadorDisponibilidade()
    resultado = verificador.verificar(vaga)
"""

from __future__ import annotations

import datetime as dt
import http.client
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Domínios cujos 404 são confiáveis (URL de vaga específica inexistente = encerrada)
DOMINIOS_404_CONFIAVEIS = frozenset({
    "jobs.bosch.com",
    "careers.fedex.com",
    "www.siemens.com",
    "jobs.dhl.com",
    "careers.microsoft.com",
    "www.nestle.com",
    "www.inesctec.pt",
    "fct.pt",
    "sigarra.up.pt",
})

# Domínios que requerem JS e não podem ser verificados via HTTP simples
DOMINIOS_NAO_VERIFICAVEIS = frozenset({
    "www.ikea.com",
    "www.sonae.pt",
})

USER_AGENT = "Mozilla/5.0 (compatible; job-availability-check/1.0; +https://github.com/nataliatravassos/oportunidades-hugo)"
TIMEOUT_SEGUNDOS = 10
INTERVALO_ENTRE_REQUISICOES = 1.0  # segundos por domínio


@dataclass
class ResultadoVerificacao:
    disponivel: bool
    evidencia: str
    status_http: int | None = None
    inconclusivo: bool = False


@dataclass
class VerificadorDisponibilidade:
    """Verificador de disponibilidade com rate limiting por domínio."""

    max_verificacoes: int = 20
    _ultimo_por_dominio: dict[str, float] = field(default_factory=dict, init=False)
    _contagem: int = field(default=0, init=False)

    def _dominio(self, url: str) -> str | None:
        try:
            return urllib.parse.urlsplit(url).hostname or None
        except Exception:
            return None

    def _aguardar_rate_limit(self, dominio: str) -> None:
        ultimo = self._ultimo_por_dominio.get(dominio, 0.0)
        espera = INTERVALO_ENTRE_REQUISICOES - (time.monotonic() - ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo_por_dominio[dominio] = time.monotonic()

    def verificar(self, vaga: dict) -> ResultadoVerificacao | None:
        """Verifica se uma vaga ainda está disponível.

        Devolve None se:
        - O link está ausente ou o domínio não pode ser verificado
        - O limite de verificações foi atingido
        """
        if self._contagem >= self.max_verificacoes:
            return None

        link = vaga.get("link")
        if not link:
            return None

        dominio = self._dominio(link)
        if not dominio:
            return None

        if dominio in DOMINIOS_NAO_VERIFICAVEIS:
            return ResultadoVerificacao(
                disponivel=True,
                evidencia="Domínio não verificável via HTTP",
                inconclusivo=True,
            )

        self._aguardar_rate_limit(dominio)
        self._contagem += 1

        try:
            req = urllib.request.Request(
                link,
                method="HEAD",
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            logger.debug("Verificação inconclusiva para %s: %s", link, e)
            return ResultadoVerificacao(
                disponivel=True,
                evidencia=f"Falha de rede: {type(e).__name__}",
                inconclusivo=True,
            )

        if status == 410:
            return ResultadoVerificacao(
                disponivel=False,
                evidencia=f"HTTP 410 Gone — vaga removida definitivamente",
                status_http=status,
            )
        if status == 404 and dominio in DOMINIOS_404_CONFIAVEIS:
            return ResultadoVerificacao(
                disponivel=False,
                evidencia=f"HTTP 404 em domínio confiável ({dominio})",
                status_http=status,
            )
        if status in (403, 429):
            return ResultadoVerificacao(
                disponivel=True,
                evidencia=f"HTTP {status} — acesso bloqueado, não comprova encerramento",
                status_http=status,
                inconclusivo=True,
            )
        if 200 <= status < 400:
            return ResultadoVerificacao(
                disponivel=True,
                evidencia=f"HTTP {status}",
                status_http=status,
            )
        # Outros erros (5xx, etc.) são inconclusivos
        return ResultadoVerificacao(
            disponivel=True,
            evidencia=f"HTTP {status} — inconclusivo",
            status_http=status,
            inconclusivo=True,
        )
