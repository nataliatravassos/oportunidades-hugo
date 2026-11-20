import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
import publicacao
from sources.base import EstadoColeta, ResultadoColeta, make_vaga


CARIMBO_ANTERIOR = "2026-11-19T07:00:00+00:00"
ROTA_FEDEX = "/industrial-engineer/job/0114F948BA2B5F95B676A19B406F93E8"


def vaga(fonte, identificador, **campos):
    dados = dict(
        titulo=f"Vaga {identificador}", empresa=fonte, cidade="Porto", fonte=fonte,
        link=f"https://example.org/{identificador}",
    )
    if fonte == "fedex":
        identificador_fedex = identificador.encode().hex().upper().ljust(32, "0")
        dados["link"] = f"https://careers.fedex.com/{identificador}/job/{identificador_fedex}"
    dados.update(campos)
    return {**make_vaga(**dados), "coletado_em": CARIMBO_ANTERIOR}


def completa(*vagas):
    return ResultadoColeta(EstadoColeta.COMPLETA, list(vagas), "Lista integral de teste")


class PublicacaoTest(unittest.TestCase):
    def setUp(self):
        diretorio = self.enterContext(TemporaryDirectory())
        self.pasta = Path(diretorio)
        self.enterContext(patch.object(main, "PASTA_DADOS", self.pasta))
        self.enterContext(patch.object(main, "logger"))

    def preparar_base(self, *vagas):
        dados = {"atualizado_em": CARIMBO_ANTERIOR, "total": len(vagas), "vagas": list(vagas)}
        (self.pasta / "vagas.json").write_text(json.dumps(dados), encoding="utf-8")
        (self.pasta / "vagas.md").write_text("Versão publicada\n", encoding="utf-8")

    def executar(self, **fontes):
        def importar(caminho):
            saida = fontes[caminho.removeprefix("sources.")]
            fetch = Mock(side_effect=saida) if isinstance(saida, Exception) else Mock(return_value=saida)
            return SimpleNamespace(fetch=fetch)

        with patch.object(main, "FONTES", list(fontes)), patch.object(main.importlib, "import_module", importar):
            return main.main()

    def ler(self, nome):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def arquivo_publicado(self):
        return tuple((self.pasta / nome).read_bytes() for nome in ("vagas.json", "vagas.md"))

    def test_falha_total_preserva_bytes_e_data_mesmo_com_fonte_manual(self):
        antiga = vaga("fedex", "antes", link="/job/antes")
        self.preparar_base(antiga)
        antes = self.arquivo_publicado()

        codigo = self.executar(fedex=TimeoutError("tempo esgotado"),
                               outros_institutos=completa(vaga("outros_institutos", "manual")))

        self.assertEqual(codigo, main.FALHA_TOTAL)
        self.assertEqual(self.arquivo_publicado(), antes)
        coleta = self.ler("coleta.json")
        self.assertEqual(coleta["estado"], "falha_total")
        self.assertFalse(coleta["dados_atualizados"])
        self.assertEqual(coleta["dados_atualizados_em"], CARIMBO_ANTERIOR)
        self.assertIn("TimeoutError", coleta["fontes"]["fedex"]["motivo"])
        self.assertEqual(coleta["fontes"]["fedex"]["preservadas"], 1)
        self.assertEqual(coleta["fontes"]["outros_institutos"]["publicadas"], 0)

    def test_falha_total_na_primeira_execucao_nao_cria_lista_vazia(self):
        self.assertEqual(self.executar(fedex=TimeoutError("tempo esgotado")), main.FALHA_TOTAL)
        self.assertEqual({p.name for p in self.pasta.iterdir()}, {"coleta.json"})
        self.assertIsNone(self.ler("coleta.json")["dados_atualizados_em"])

    def test_falha_de_uma_fonte_preserva_e_corrige_links_legados(self):
        antiga = vaga("fedex", "antes", link=ROTA_FEDEX + "?utm_source=CareerSiteOrganic&job=123")
        ikea = vaga("ikea", "antiga")
        self.preparar_base(antiga, ikea)
        nova = vaga("ikea", "nova")
        self.assertEqual(self.executar(fedex=TimeoutError("pagina"), ikea=completa(nova)), 0)

        dados = self.ler("vagas.json")
        link = "https://careers.fedex.com" + ROTA_FEDEX + "?job=123"
        self.assertEqual(dados["vagas"], [{**antiga, "link": link}, {**ikea, "verificacao_pendente": True}, nova])
        self.assertIn(link, (self.pasta / "vagas.md").read_text(encoding="utf-8"))
        self.assertEqual(self.ler("coleta.json")["estado"], "parcial")

    def test_coleta_parcial_acrescenta_vagas_e_reexecucao_e_idempotente(self):
        antiga = vaga("fedex", "antes")
        self.preparar_base(antiga, vaga("fedex", "ausente"))
        nova = vaga("fedex", "nova")
        incompleta = vaga("fedex", "antes", titulo="Título incompleto")

        resultado = ResultadoColeta(EstadoColeta.PARCIAL, [incompleta, nova], "timeout na página 2")
        self.assertEqual(self.executar(fedex=resultado), 0)
        dados = self.ler("vagas.json")
        self.assertEqual(dados["total"], 3)
        self.assertIn(antiga, dados["vagas"])
        self.assertTrue(next(v for v in dados["vagas"] if v["titulo"] == "Vaga ausente")["verificacao_pendente"])
        antes = self.arquivo_publicado()
        reexecucao = ResultadoColeta(EstadoColeta.PARCIAL, [incompleta, nova], "timeout novamente")
        self.assertEqual(self.executar(fedex=reexecucao), 0)
        self.assertEqual(self.arquivo_publicado(), antes)
        self.assertFalse(self.ler("coleta.json")["dados_atualizados"])

    def test_reexecucao_completa_com_mesmos_dados_mantem_data(self):
        anterior = vaga("ikea", "antes")
        self.preparar_base(anterior)
        recoletada = {**anterior, "coletado_em": "2099-01-01T00:00:00+00:00"}
        self.assertEqual(self.executar(ikea=completa(recoletada)), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [recoletada])
        coleta = self.ler("coleta.json")
        self.assertEqual(coleta["estado"], "sucesso")
        self.assertFalse(coleta["dados_atualizados"])
        self.assertEqual(coleta["dados_atualizados_em"], CARIMBO_ANTERIOR)

    def test_zero_confirmado_sinaliza_vagas_sem_apagar_e_sem_mudar_data_da_ultima_observacao(self):
        ikea = vaga("ikea", "mantida")
        antiga = vaga("inesctec", "anterior")
        self.preparar_base(antiga, ikea)
        zero = ResultadoColeta(EstadoColeta.ZERO, motivo="API de editais ativos retornou []")
        self.assertEqual(self.executar(inesctec=zero, ikea=TimeoutError("página")), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [ikea, {**antiga, "verificacao_pendente": True}])
        self.assertEqual(self.ler("coleta.json")["fontes"]["inesctec"]["estado"], "zero_confirmado")

    def test_coleta_completa_nao_remove_vaga_e_reaparecimento_limpa_a_marca(self):
        ausente = vaga("inesctec", "ausente")
        presente = vaga("inesctec", "presente")
        self.preparar_base(ausente, presente)
        self.assertEqual(self.executar(inesctec=completa(presente)), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [{**ausente, "verificacao_pendente": True}, presente])
        self.assertIn("por confirmar", (self.pasta / "vagas.md").read_text(encoding="utf-8"))

        agora = {**ausente, "coletado_em": "2026-11-20T07:00:00+00:00"}
        parcial = ResultadoColeta(EstadoColeta.PARCIAL, [agora, presente], "Cobertura parcial")
        self.assertEqual(self.executar(inesctec=parcial), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [agora, presente])
        self.assertEqual(self.ler("coleta.json")["fontes"]["inesctec"]["por_confirmar"], 0)

    def test_destino_legado_duvidoso_fica_sem_link_ate_reaparecer_com_mesma_referencia(self):
        antiga = vaga("fedex", "antes", link="/jobs?busca=porto", categoria="RC789529")
        self.preparar_base(antiga)
        ikea = vaga("ikea", "nova")
        self.assertEqual(self.executar(fedex=TimeoutError("pagina"), ikea=completa(ikea)), 0)
        dados = self.ler("vagas.json")
        self.assertEqual(dados["vagas"][0], {**antiga, "link": None, "link_original": antiga["link"]})
        self.assertIn("Link por confirmar", (self.pasta / "vagas.md").read_text(encoding="utf-8"))

        reencontrada = {**antiga, "link": "https://careers.fedex.com" + ROTA_FEDEX,
                        "coletado_em": "2026-11-20T07:00:00+00:00"}
        parcial = ResultadoColeta(EstadoColeta.PARCIAL, [reencontrada], "Paginação incerta")
        self.assertEqual(self.executar(fedex=parcial), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [reencontrada, ikea])

    def test_lista_vazia_inesperada_nao_remove_dados(self):
        self.preparar_base(vaga("fedex", "antes"))
        antes = self.arquivo_publicado()
        self.assertEqual(self.executar(fedex=completa()), main.FALHA_TOTAL)
        self.assertEqual(self.arquivo_publicado(), antes)
        self.assertEqual(self.ler("coleta.json")["fontes"]["fedex"]["estado"], "falha")

    def test_link_invalido_rebaixa_sucesso_e_preserva_vaga_anterior(self):
        antiga = vaga("fedex", "antiga")
        nova = vaga("fedex", "nova")
        invalida = vaga("fedex", "erro", link="javascript:alert(1)")
        self.preparar_base(antiga)

        self.assertEqual(self.executar(fedex=completa(nova, invalida)), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [{**antiga, "verificacao_pendente": True}, nova])
        fonte = self.ler("coleta.json")["fontes"]["fedex"]
        self.assertEqual(fonte["estado"], "parcial")
        self.assertEqual(fonte["rejeitadas"], 1)
        self.assertIn("Link de candidatura inválido", fonte["motivo"])

    def test_valida_publicacao_antes_de_substituir_arquivos(self):
        self.preparar_base(vaga("ikea", "antes"))
        antes = self.arquivo_publicado()
        invalido = {"atualizado_em": CARIMBO_ANTERIOR, "total": 1, "vagas": []}
        with self.assertRaises(ValueError):
            publicacao.publicar(self.pasta, invalido, {})
        self.assertEqual(self.arquivo_publicado(), antes)
        self.assertFalse((self.pasta / "coleta.json").exists())

    def test_falha_ao_substituir_segundo_arquivo_restaura_o_primeiro(self):
        self.preparar_base(vaga("ikea", "antes"))
        antes = self.arquivo_publicado()
        substituir = os.replace

        def falhar_na_lista(origem, destino):
            if Path(destino).name == "vagas.json":
                raise OSError("falha simulada")
            substituir(origem, destino)

        with patch.object(publicacao.os, "replace", side_effect=falhar_na_lista):
            with self.assertRaisesRegex(OSError, "falha simulada"):
                self.executar(ikea=completa(vaga("ikea", "nova")))

        self.assertEqual(self.arquivo_publicado(), antes)
        self.assertFalse((self.pasta / "coleta.json").exists())

    def test_base_malformada_interrompe_publicacao(self):
        self.preparar_base(vaga("ikea", "antes"))
        (self.pasta / "vagas.json").write_text("{", encoding="utf-8")
        antes = self.arquivo_publicado()

        with self.assertRaises(json.JSONDecodeError):
            self.executar(ikea=completa(vaga("ikea", "nova")))

        self.assertEqual(self.arquivo_publicado(), antes)

    def test_erro_ao_publicar_diagnostico_restaura_ambos_os_arquivos(self):
        self.preparar_base(vaga("ikea", "antes"))
        antes = self.arquivo_publicado()
        diagnostico = self.pasta / "coleta.json"
        diagnostico.write_text('{"estado":"sucesso"}', encoding="utf-8")
        substituir = os.replace

        def falhar_no_diagnostico(origem, destino):
            if Path(destino) == diagnostico:
                raise OSError("falha no diagnóstico")
            substituir(origem, destino)

        with patch.object(publicacao.os, "replace", side_effect=falhar_no_diagnostico):
            with self.assertRaisesRegex(OSError, "falha no diagnóstico"):
                self.executar(ikea=completa(vaga("ikea", "nova")))

        self.assertEqual(self.arquivo_publicado(), antes)
        self.assertEqual(self.ler("coleta.json"), {"estado": "sucesso"})


if __name__ == "__main__":
    unittest.main()
