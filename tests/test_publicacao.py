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


def vaga(fonte, identificador, **campos):
    dados = dict(
        titulo=f"Vaga {identificador}", empresa=fonte, cidade="Porto", fonte=fonte,
        link=f"https://example.org/{identificador}",
    )
    dados.update(campos)
    return make_vaga(**dados)


def completa(*vagas):
    return ResultadoColeta(EstadoColeta.COMPLETA, list(vagas))


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
        antiga = vaga("fedex", "antes", link="/job/antes?job=123")
        self.preparar_base(antiga, vaga("ikea", "antiga"))
        nova = vaga("ikea", "nova")
        self.assertEqual(self.executar(fedex=TimeoutError("pagina"), ikea=completa(nova)), 0)

        dados = self.ler("vagas.json")
        link = "https://careers.fedex.com/job/antes?job=123"
        self.assertEqual(dados["vagas"], [{**antiga, "link": link}, nova])
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
        antes = self.arquivo_publicado()

        nova_recoletada = {**nova, "coletado_em": "2099-01-01T00:00:00+00:00"}
        reexecucao = ResultadoColeta(EstadoColeta.PARCIAL, [nova_recoletada], "timeout novamente")
        self.assertEqual(self.executar(fedex=reexecucao), 0)
        self.assertEqual(self.arquivo_publicado(), antes)
        self.assertFalse(self.ler("coleta.json")["dados_atualizados"])

    def test_reexecucao_completa_com_mesmos_dados_mantem_data(self):
        anterior = vaga("ikea", "antes")
        self.preparar_base(anterior)
        antes = self.arquivo_publicado()
        recoletada = {**anterior, "coletado_em": "2099-01-01T00:00:00+00:00"}
        self.assertEqual(self.executar(ikea=completa(recoletada)), 0)
        self.assertEqual(self.arquivo_publicado(), antes)
        coleta = self.ler("coleta.json")
        self.assertEqual(coleta["estado"], "sucesso")
        self.assertFalse(coleta["dados_atualizados"])
        self.assertEqual(coleta["dados_atualizados_em"], CARIMBO_ANTERIOR)

    def test_zero_confirmado_limpa_somente_a_propria_fonte(self):
        ikea = vaga("ikea", "mantida")
        self.preparar_base(vaga("inesctec", "anterior"), ikea)
        zero = ResultadoColeta(EstadoColeta.ZERO, motivo="API de editais ativos retornou []")
        self.assertEqual(self.executar(inesctec=zero, ikea=TimeoutError("página")), 0)
        self.assertEqual(self.ler("vagas.json")["vagas"], [ikea])
        self.assertEqual(self.ler("coleta.json")["fontes"]["inesctec"]["estado"], "zero_confirmado")

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
        self.assertEqual(self.ler("vagas.json")["vagas"], [antiga, nova])
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


if __name__ == "__main__":
    unittest.main()
