import unittest
from pathlib import Path

from config import VERIFICADOR_ATIVO


class InterfaceTest(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(__file__).resolve().parents[1]
        self.html = (self.raiz / "index.html").read_text(encoding="utf-8")

    def test_painel_tem_filtros_reais_de_situacao(self):
        for chave in ("observada", "por_confirmar", "encerrada"):
            self.assertIn(f"[\"{chave}\"", self.html)
        self.assertIn("Observada", self.html)
        self.assertIn("Por confirmar", self.html)
        self.assertIn("Encerrada", self.html)

    def test_encerradas_tem_secao_separada_de_historico(self):
        self.assertIn("Histórico de vagas encerradas", self.html)
        self.assertIn("situacaoDe(v) === \"encerrada\"", self.html)

    def test_app_mantem_service_worker_e_manifest(self):
        self.assertIn('href="manifest.json"', self.html)
        self.assertIn('navigator.serviceWorker.register("sw.js")', self.html)
        self.assertTrue((self.raiz / "manifest.json").is_file())
        self.assertTrue((self.raiz / "sw.js").is_file())

    def test_verificador_esta_desativado_por_padrao(self):
        self.assertFalse(VERIFICADOR_ATIVO)


if __name__ == "__main__":
    unittest.main()
