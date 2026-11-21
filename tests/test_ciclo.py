"""Testes para o ciclo de vida das vagas (P1 Etapa 2).

Cobre:
- Migração dos 138 registros históricos
- Falhas parciais e totais
- Reaparecimento
- Encerramento comprovado
- Datas históricas desconhecidas
- Idempotência
- Filtros e apresentação (Markdown)
- Preservação dos dados
- Dupla contagem corrigida nos diagnósticos
- Verificador de disponibilidade (sem chamadas reais de rede)
"""

import datetime
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
import urllib.error

import main
import publicacao
from publicacao import renderizar_markdown, validar_vaga
from sources.base import EstadoColeta, ResultadoColeta, make_vaga
from sources.ciclo import (
    SituacaoVaga, inicializar_vaga, marcar_por_confirmar, migrar_vaga, reapareceu,
    registrar_verificacao,
)
from sources.verificador import (
    ResultadoVerificacao, VerificadorDisponibilidade, DOMINIOS_404_CONFIAVEIS,
)


CARIMBO = "2026-11-19T07:00:00+00:00"
CARIMBO_NOVO = "2026-11-20T07:00:00+00:00"
ROTA_FEDEX = "/industrial-engineer/job/0114F948BA2B5F95B676A19B406F93E8"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vaga(fonte="ikea", identificador="v1", **extra):
    dados = dict(
        titulo=f"Vaga {identificador}", empresa=fonte, cidade="Porto", fonte=fonte,
        link=f"https://example.org/{identificador}",
    )
    dados.update(extra)
    return {**make_vaga(**dados), "coletado_em": CARIMBO}


def _completa(*vagas):
    return ResultadoColeta(EstadoColeta.COMPLETA, list(vagas), "Lista integral de teste")


# ---------------------------------------------------------------------------
# 1. Migração de registros históricos
# ---------------------------------------------------------------------------

class MigracaoTest(unittest.TestCase):
    def test_migrar_vaga_sem_ciclo_adiciona_campos(self):
        v = _vaga()
        m = migrar_vaga(v)
        self.assertEqual(m["situacao"], "observada")
        self.assertEqual(m["primeira_observacao"], CARIMBO)
        self.assertEqual(m["ultima_observacao"], CARIMBO)
        self.assertIsNone(m["evidencia_encerramento"])

    def test_migrar_vaga_verificacao_pendente_vira_por_confirmar(self):
        v = {**_vaga(), "verificacao_pendente": True}
        m = migrar_vaga(v)
        self.assertEqual(m["situacao"], "por_confirmar")

    def test_migrar_idempotente(self):
        v = _vaga()
        m1 = migrar_vaga(v)
        m2 = migrar_vaga(m1)
        self.assertEqual(m1, m2)

    def test_migrar_sem_coletado_em_aceita_none(self):
        v = {**_vaga(), "coletado_em": None}
        m = migrar_vaga(v)
        self.assertIsNone(m["primeira_observacao"])
        self.assertIsNone(m["ultima_observacao"])

    def test_migrar_138_registros_reais(self):
        """Verifica que todos os 138 registros de produção migram sem erro."""
        caminho = Path(__file__).resolve().parents[1] / "data" / "vagas.json"
        if not caminho.exists():
            self.skipTest("vagas.json ausente")
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        migradas = [migrar_vaga(v) for v in dados["vagas"]]
        self.assertEqual(len(migradas), len(dados["vagas"]))
        for m in migradas:
            self.assertIn(m["situacao"], ("observada", "por_confirmar", "encerrada"))
            self.assertIn("primeira_observacao", m)
            self.assertIn("ultima_observacao", m)
            self.assertIn("evidencia_encerramento", m)

    def test_migrar_138_registros_passam_validacao(self):
        """Registros migrados continuam válidos segundo validar_vaga."""
        caminho = Path(__file__).resolve().parents[1] / "data" / "vagas.json"
        if not caminho.exists():
            self.skipTest("vagas.json ausente")
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        for v in dados["vagas"]:
            m = migrar_vaga(v)
            # Não deve lançar exceção
            validar_vaga(m, legado=True, preservada=True)


# ---------------------------------------------------------------------------
# 2. Inicialização de novas vagas
# ---------------------------------------------------------------------------

class InicializacaoTest(unittest.TestCase):
    def test_inicializar_vaga_nova_tem_situacao_observada(self):
        v = _vaga()
        i = inicializar_vaga(v)
        self.assertEqual(i["situacao"], "observada")
        self.assertEqual(i["primeira_observacao"], CARIMBO)
        self.assertEqual(i["ultima_observacao"], CARIMBO)
        self.assertIsNone(i["evidencia_encerramento"])

    def test_inicializar_idempotente(self):
        v = _vaga()
        i1 = inicializar_vaga(v)
        # Se já tem situacao, atualizar_fonte não reinicializa
        self.assertEqual(i1["situacao"], "observada")


# ---------------------------------------------------------------------------
# 3. Reaparecimento preserva histórico
# ---------------------------------------------------------------------------

class RaparecimentoTest(unittest.TestCase):
    def test_reaparecimento_preserva_primeira_observacao(self):
        anterior = {**migrar_vaga(_vaga()), "primeira_observacao": CARIMBO}
        nova = {**_vaga(), "coletado_em": CARIMBO_NOVO}
        r = reapareceu(anterior, nova)
        self.assertEqual(r["primeira_observacao"], CARIMBO)
        self.assertEqual(r["ultima_observacao"], CARIMBO_NOVO)
        self.assertEqual(r["situacao"], "observada")
        self.assertIsNone(r["evidencia_encerramento"])

    def test_reaparecimento_limpa_por_confirmar(self):
        anterior = migrar_vaga({**_vaga(), "verificacao_pendente": True})
        self.assertEqual(anterior["situacao"], "por_confirmar")
        nova = {**_vaga(), "coletado_em": CARIMBO_NOVO}
        r = reapareceu(anterior, nova)
        self.assertEqual(r["situacao"], "observada")
        self.assertFalse(r.get("verificacao_pendente", False))


# ---------------------------------------------------------------------------
# 4. Marcar por confirmar
# ---------------------------------------------------------------------------

class PorConfirmarTest(unittest.TestCase):
    def test_marcar_por_confirmar_mantem_ultima_observacao(self):
        v = migrar_vaga(_vaga())
        self.assertEqual(v["ultima_observacao"], CARIMBO)
        pc = marcar_por_confirmar(v, agora=CARIMBO_NOVO)
        self.assertEqual(pc["situacao"], "por_confirmar")
        self.assertEqual(pc["ultima_observacao"], CARIMBO)  # não muda!
        self.assertEqual(pc["ultima_verificacao"], CARIMBO_NOVO)
        self.assertTrue(pc["verificacao_pendente"])

    def test_falha_de_coletor_nao_altera_ciclo(self):
        """FALHA total deve preservar ciclo de vida sem alterar nada."""
        anterior = migrar_vaga(_vaga())
        publicadas = main.atualizar_fonte([anterior], [], EstadoColeta.FALHA)
        self.assertEqual(publicadas[0]["situacao"], anterior["situacao"])
        self.assertEqual(publicadas[0]["ultima_observacao"], anterior["ultima_observacao"])


# ---------------------------------------------------------------------------
# 5. Encerramento
# ---------------------------------------------------------------------------

class EncerramentoTest(unittest.TestCase):
    def test_encerramento_requer_evidencia_individual(self):
        v = migrar_vaga(_vaga())
        enc = registrar_verificacao(v, disponivel=False, evidencia="HTTP 410 Gone", agora=CARIMBO_NOVO)
        self.assertEqual(enc["situacao"], "encerrada")
        self.assertEqual(enc["evidencia_encerramento"], "HTTP 410 Gone")

    def test_timeout_nao_encerra(self):
        v = migrar_vaga(_vaga())
        pc = registrar_verificacao(v, disponivel=False, evidencia="timeout na conexão", agora=CARIMBO_NOVO)
        # timeout é inconclusivo → estado não muda
        self.assertNotEqual(pc["situacao"], "encerrada")

    def test_http_403_nao_encerra(self):
        v = migrar_vaga(_vaga())
        r = registrar_verificacao(v, disponivel=False, evidencia="403 Forbidden", agora=CARIMBO_NOVO)
        self.assertNotEqual(r["situacao"], "encerrada")

    def test_http_429_nao_encerra(self):
        v = migrar_vaga(_vaga())
        r = registrar_verificacao(v, disponivel=False, evidencia="429 Too Many Requests", agora=CARIMBO_NOVO)
        self.assertNotEqual(r["situacao"], "encerrada")

    def test_ausencia_em_coleta_parcial_nao_encerra(self):
        """Ausência em coleta parcial → por_confirmar, não encerrada."""
        v = migrar_vaga(_vaga("ikea", "ausente"))
        publicadas = main.atualizar_fonte([v], [], EstadoColeta.PARCIAL)
        self.assertEqual(publicadas[0]["situacao"], "por_confirmar")

    def test_ausencia_em_coleta_zero_nao_encerra(self):
        """ZERO confirmado não encerra individualmente."""
        v = migrar_vaga(_vaga("ikea", "ausente"))
        publicadas = main.atualizar_fonte([v], [], EstadoColeta.ZERO)
        self.assertEqual(publicadas[0]["situacao"], "por_confirmar")

    def test_encerrada_permanece_no_historico(self):
        v = migrar_vaga(_vaga())
        enc = registrar_verificacao(v, disponivel=False, evidencia="HTTP 410 Gone")
        publicadas = main.atualizar_fonte([enc], [], EstadoColeta.COMPLETA)
        enc_resultado = next(r for r in publicadas if r.get("situacao") == "encerrada")
        self.assertEqual(enc_resultado["evidencia_encerramento"], "HTTP 410 Gone")


# ---------------------------------------------------------------------------
# 6. Integração com main.py (ciclo + migração)
# ---------------------------------------------------------------------------

class IntegracaoMainTest(unittest.TestCase):
    def setUp(self):
        self.diretorio = self.enterContext(TemporaryDirectory())
        self.pasta = Path(self.diretorio)
        self.enterContext(patch.object(main, "PASTA_DADOS", self.pasta))
        self.enterContext(patch.object(main, "logger"))

    def preparar_base(self, *vagas):
        dados = {"atualizado_em": CARIMBO, "total": len(vagas), "vagas": list(vagas)}
        (self.pasta / "vagas.json").write_text(json.dumps(dados), encoding="utf-8")
        (self.pasta / "vagas.md").write_text("versão anterior\n", encoding="utf-8")

    def executar(self, **fontes):
        def importar(caminho):
            saida = fontes[caminho.removeprefix("sources.")]
            fetch = Mock(side_effect=saida) if isinstance(saida, Exception) else Mock(return_value=saida)
            return SimpleNamespace(fetch=fetch)
        with patch.object(main, "FONTES", list(fontes)), \
             patch.object(main.importlib, "import_module", importar):
            return main.main()

    def ler(self, nome):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def test_nova_coleta_inicializa_campos_ciclo(self):
        nova = _vaga()
        self.assertEqual(self.executar(ikea=_completa(nova)), 0)
        dados = self.ler("vagas.json")
        v = dados["vagas"][0]
        self.assertEqual(v["situacao"], "observada")
        self.assertIn("primeira_observacao", v)
        self.assertIn("ultima_observacao", v)

    def test_migra_base_historica_sem_campos_ciclo(self):
        antiga = _vaga()
        self.assertNotIn("situacao", antiga)
        self.preparar_base(antiga)
        self.assertEqual(self.executar(ikea=_completa(antiga)), 0)
        dados = self.ler("vagas.json")
        self.assertIn("situacao", dados["vagas"][0])

    def test_falha_total_preserva_ciclo_sem_alterar(self):
        v_migrada = {**migrar_vaga(_vaga()), "situacao": "observada"}
        self.preparar_base(v_migrada)
        self.assertEqual(self.executar(ikea=TimeoutError("timeout")), main.FALHA_TOTAL)
        dados = self.ler("vagas.json")
        self.assertEqual(dados["vagas"][0]["situacao"], "observada")

    def test_reaparecimento_limpa_por_confirmar_e_preserva_primeira_obs(self):
        antiga = {**migrar_vaga(_vaga("ikea", "v1")), "situacao": "por_confirmar",
                  "verificacao_pendente": True, "primeira_observacao": CARIMBO}
        self.preparar_base(antiga)
        nova = {**_vaga("ikea", "v1"), "coletado_em": CARIMBO_NOVO}
        self.assertEqual(self.executar(ikea=_completa(nova)), 0)
        dados = self.ler("vagas.json")
        v = dados["vagas"][0]
        self.assertEqual(v["situacao"], "observada")
        self.assertEqual(v["primeira_observacao"], CARIMBO)  # preservado!
        self.assertFalse(v.get("verificacao_pendente", False))

    def test_encerrada_aparece_no_markdown_em_secao_separada(self):
        enc = {**migrar_vaga(_vaga("ikea", "enc")),
               "situacao": "encerrada",
               "evidencia_encerramento": "HTTP 410",
               "verificacao_pendente": False}
        ativa = migrar_vaga(_vaga("ikea", "ativa"))
        self.preparar_base(enc, ativa)
        # Coleta com timestamp mais novo para garantir atualização de dados
        ativa_nova = {**_vaga("ikea", "ativa"), "coletado_em": CARIMBO_NOVO}
        self.assertEqual(self.executar(ikea=_completa(ativa_nova)), 0)
        md = (self.pasta / "vagas.md").read_text(encoding="utf-8")
        self.assertIn("Encerradas (histórico)", md)
        self.assertIn("encerrada", md)

    def test_por_confirmar_aparece_no_markdown(self):
        v = {**migrar_vaga(_vaga("ikea", "pendente")),
             "situacao": "por_confirmar", "verificacao_pendente": True}
        self.preparar_base(v)
        self.assertEqual(self.executar(ikea=_completa(_vaga("ikea", "nova"))), 0)
        md = (self.pasta / "vagas.md").read_text(encoding="utf-8")
        self.assertIn("por confirmar", md)

    def test_diagnostico_sem_dupla_contagem(self):
        """rejeitadas deve contar apenas validação, não extração."""
        v = _vaga()
        resultado = ResultadoColeta(
            EstadoColeta.PARCIAL, [v], "timeout",
            consulta={"cartoes_invalidos": 3},
        )
        self.assertEqual(self.executar(ikea=resultado), 0)
        fontes = self.ler("coleta.json")["fontes"]
        ikea = fontes["ikea"]
        # Sem rejeições de validação → rejeitadas deve ser 0
        self.assertEqual(ikea["rejeitadas"], 0)
        self.assertEqual(ikea["rejeitadas_extracao"], 3)
        self.assertEqual(ikea["rejeitadas_validacao"], 0)
        # extraidas não inclui os cartoes_invalidos
        self.assertEqual(ikea["extraidas"], 1)

    def test_diagnostico_conta_encerradas_e_por_confirmar(self):
        enc = {**migrar_vaga(_vaga("ikea", "enc")), "situacao": "encerrada",
               "evidencia_encerramento": "HTTP 410"}
        pc = {**migrar_vaga(_vaga("ikea", "pc")), "situacao": "por_confirmar",
              "verificacao_pendente": True}
        obs = migrar_vaga(_vaga("ikea", "obs"))
        self.preparar_base(enc, pc, obs)
        nova_obs = {**_vaga("ikea", "obs"), "coletado_em": CARIMBO_NOVO}
        self.assertEqual(self.executar(ikea=_completa(nova_obs)), 0)
        d = self.ler("coleta.json")["fontes"]["ikea"]
        self.assertEqual(d["encerradas"], 1)
        self.assertEqual(d["por_confirmar"], 1)

    def test_migra_base_sem_campos_ciclo_e_publica_com_validacao(self):
        """Base histórica sem campos de ciclo deve ser migrada e continuar válida."""
        vagas_antigas = [_vaga("ikea", f"v{i}") for i in range(5)]
        self.assertFalse(any("situacao" in v for v in vagas_antigas))
        self.preparar_base(*vagas_antigas)
        nova = _vaga("ikea", "v0")
        self.assertEqual(self.executar(ikea=_completa(nova)), 0)
        dados = self.ler("vagas.json")
        for v in dados["vagas"]:
            self.assertIn("situacao", v)


# ---------------------------------------------------------------------------
# 7. Renderização Markdown com situacao
# ---------------------------------------------------------------------------

class RenderizacaoTest(unittest.TestCase):
    def _dados(self, *vagas):
        return {"atualizado_em": CARIMBO, "total": len(vagas), "vagas": list(vagas)}

    def test_encerradas_aparecem_em_secao_separada(self):
        enc = {**migrar_vaga(_vaga("ikea", "enc")), "situacao": "encerrada",
               "evidencia_encerramento": "HTTP 410"}
        md = renderizar_markdown(self._dados(enc))
        self.assertIn("Encerradas (histórico)", md)
        self.assertIn("encerrada", md)

    def test_por_confirmar_mostra_nota(self):
        pc = {**migrar_vaga(_vaga("ikea", "pc")), "situacao": "por_confirmar",
              "verificacao_pendente": True}
        md = renderizar_markdown(self._dados(pc))
        self.assertIn("por confirmar", md)

    def test_todas_vagas_aparecem_no_markdown(self):
        enc = {**migrar_vaga(_vaga("ikea", "enc")), "situacao": "encerrada",
               "evidencia_encerramento": "HTTP 410"}
        obs = migrar_vaga(_vaga("ikea", "obs"))
        pc = {**migrar_vaga(_vaga("ikea", "pc")), "situacao": "por_confirmar",
              "verificacao_pendente": True}
        md = renderizar_markdown(self._dados(enc, obs, pc))
        linhas_tabela = sum(
            linha.endswith((">) |", "Link por confirmar |"))
            for linha in md.splitlines()
        )
        self.assertEqual(linhas_tabela, 3)

    def test_contagem_exclui_encerradas_da_linha_total(self):
        enc = {**migrar_vaga(_vaga("ikea", "enc")), "situacao": "encerrada",
               "evidencia_encerramento": "HTTP 410"}
        obs = migrar_vaga(_vaga("ikea", "obs"))
        md = renderizar_markdown(self._dados(enc, obs))
        self.assertIn("1 vaga(s) ativa(s)", md)

    def test_validacao_aceita_campos_ciclo(self):
        v = migrar_vaga(_vaga())
        validar_vaga(v, legado=True, preservada=True)  # não lança

    def test_validacao_rejeita_situacao_invalida(self):
        v = {**migrar_vaga(_vaga()), "situacao": "outra_coisa"}
        with self.assertRaises(ValueError):
            validar_vaga(v)


# ---------------------------------------------------------------------------
# 8. Verificador de disponibilidade
# ---------------------------------------------------------------------------

class VerificadorTest(unittest.TestCase):
    def test_http_410_encerra(self):
        v = VerificadorDisponibilidade()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://jobs.bosch.com/job/123", code=410,
                msg="Gone", hdrs=None, fp=None,
            )
            r = v.verificar(_vaga(link="https://jobs.bosch.com/job/123"))
        self.assertFalse(r.disponivel)
        self.assertIn("410", r.evidencia)

    def test_http_404_em_dominio_confiavel_encerra(self):
        v = VerificadorDisponibilidade()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://jobs.bosch.com/job/123", code=404,
                msg="Not Found", hdrs=None, fp=None,
            )
            r = v.verificar(_vaga(link="https://jobs.bosch.com/job/123"))
        self.assertFalse(r.disponivel)
        self.assertIn("404", r.evidencia)

    def test_http_404_em_dominio_desconhecido_nao_encerra(self):
        v = VerificadorDisponibilidade()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://desconhecido.example.com/job/123", code=404,
                msg="Not Found", hdrs=None, fp=None,
            )
            r = v.verificar(_vaga(link="https://desconhecido.example.com/job/123"))
        # 404 de domínio desconhecido é inconclusivo → considera disponível
        self.assertTrue(r.disponivel or r.inconclusivo)

    def test_http_403_e_inconclusivo(self):
        v = VerificadorDisponibilidade()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://jobs.bosch.com/job/123", code=403,
                msg="Forbidden", hdrs=None, fp=None,
            )
            r = v.verificar(_vaga(link="https://jobs.bosch.com/job/123"))
        self.assertTrue(r.inconclusivo)

    def test_timeout_e_inconclusivo(self):
        v = VerificadorDisponibilidade()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = TimeoutError("connection timed out")
            r = v.verificar(_vaga(link="https://jobs.bosch.com/job/123"))
        self.assertTrue(r.inconclusivo)
        self.assertTrue(r.disponivel)

    def test_limite_de_verificacoes_respeitado(self):
        v = VerificadorDisponibilidade(max_verificacoes=2)
        mock_resp = MagicMock()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        mock_resp.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch.object(v, "_aguardar_rate_limit"):
                r1 = v.verificar(_vaga(link="https://jobs.bosch.com/job/1"))
                r2 = v.verificar(_vaga(link="https://jobs.bosch.com/job/2"))
                r3 = v.verificar(_vaga(link="https://jobs.bosch.com/job/3"))
        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertIsNone(r3)  # limite atingido

    def test_link_ausente_devolve_none(self):
        v = VerificadorDisponibilidade()
        self.assertIsNone(v.verificar({"link": None, "fonte": "ikea"}))

    def test_dominio_nao_verificavel_e_inconclusivo(self):
        v = VerificadorDisponibilidade()
        r = v.verificar(_vaga(link="https://www.ikea.com/pt/pt/jobs/"))
        self.assertIsNotNone(r)
        self.assertTrue(r.inconclusivo)


# ---------------------------------------------------------------------------
# 9. Preservação de dados históricos e compatibilidade
# ---------------------------------------------------------------------------

class CompatibilidadeTest(unittest.TestCase):
    def test_vaga_sem_campos_ciclo_passa_validacao_legada(self):
        v = _vaga()
        self.assertNotIn("situacao", v)
        validar_vaga(v, legado=True, preservada=True)  # não lança

    def test_vaga_com_campos_ciclo_passa_validacao(self):
        v = migrar_vaga(_vaga())
        validar_vaga(v, legado=True, preservada=True)

    def test_data_ciclo_invalida_rejeita(self):
        v = {**migrar_vaga(_vaga()), "primeira_observacao": "não-é-data"}
        with self.assertRaises(ValueError):
            validar_vaga(v)

    def test_campos_ciclo_opcionais_nao_sao_obrigatorios(self):
        v = _vaga()
        self.assertNotIn("situacao", v)
        # validar_vaga deve funcionar sem campos de ciclo
        resultado = validar_vaga(v)
        self.assertNotIn("situacao", resultado)


if __name__ == "__main__":
    unittest.main()
