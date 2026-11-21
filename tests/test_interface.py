import unittest
from pathlib import Path
import json
import subprocess

from config import VERIFICADOR_ATIVO


class InterfaceTest(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(__file__).resolve().parents[1]
        self.html = (self.raiz / "index.html").read_text(encoding="utf-8")

    def test_painel_tem_filtros_reais_de_situacao(self):
        for chave in ("observada", "por_confirmar", "encerrada"):
            self.assertIn(f"[\"{chave}\"", self.html)
        for rotulo in ("Escritório", "A conferir", "Operacional"):
            self.assertIn(rotulo, self.html)
        self.assertIn("Observada", self.html)
        self.assertIn("Por confirmar", self.html)
        self.assertIn("Encerrada", self.html)

    def test_filtros_combinados_da_funcao_real_do_aplicativo(self):
        inicio = self.html.index("function filtrarVagas")
        resto = self.html[inicio:]
        profundidade = 0
        fim = None
        for i, caractere in enumerate(resto):
            if caractere == "{":
                profundidade += 1
            elif caractere == "}":
                profundidade -= 1
                if profundidade == 0:
                    fim = i + 1
                    break
        funcao = resto[:fim]
        vagas = [
            {"classificacao": "escritorio", "situacao": "observada"},
            {"classificacao": "escritorio", "situacao": "por_confirmar"},
            {"classificacao": "operacional", "situacao": "observada"},
            {"classificacao": "escritorio", "situacao": "encerrada"},
        ]
        script = funcao + "\nprocess.stdout.write(JSON.stringify(filtrarVagas(" + json.dumps(vagas) + ", process.argv[1], process.argv[2])));"
        casos = [
            ("escritorio", "observada", 1),
            ("operacional", "observada", 1),
            ("escritorio", "encerrada", 1),
            ("todas", "por_confirmar", 1),
            ("todas", "todas", 3),
            ("escritorio", "todas", 2),
        ]
        for classificacao, situacao, esperado in casos:
            resultado = subprocess.run(
                ["node", "-e", script, classificacao, situacao],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(len(json.loads(resultado.stdout)), esperado)

    def test_encerradas_tem_secao_separada_de_historico(self):
        self.assertIn("Histórico de vagas encerradas", self.html)
        self.assertIn("filtroSituacao === \"encerrada\"", self.html)
        self.assertIn("situacaoAtual !== \"encerrada\"", self.html)

    def test_visualizacao_inicial_exclui_encerradas(self):
        vagas = [
            {"classificacao": "escritorio", "situacao": "observada"},
            {"classificacao": "operacional", "situacao": "por_confirmar"},
            {"classificacao": "escritorio", "situacao": "encerrada"},
        ]
        inicio = self.html.index("function filtrarVagas")
        resto = self.html[inicio:]
        profundidade = 0
        fim = None
        for i, caractere in enumerate(resto):
            if caractere == "{":
                profundidade += 1
            elif caractere == "}":
                profundidade -= 1
                if profundidade == 0:
                    fim = i + 1
                    break
        funcao = resto[:fim]
        script = funcao + "\nprocess.stdout.write(JSON.stringify(filtrarVagas(" + json.dumps(vagas) + ", 'todas', 'todas')));"
        resultado = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True,
        )
        exibidas = json.loads(resultado.stdout)
        self.assertEqual(len(exibidas), 2)
        self.assertFalse(any(v["situacao"] == "encerrada" for v in exibidas))

    def test_app_mantem_service_worker_e_manifest(self):
        self.assertIn('href="manifest.json"', self.html)
        self.assertIn('navigator.serviceWorker.register("sw.js")', self.html)
        self.assertTrue((self.raiz / "manifest.json").is_file())
        self.assertTrue((self.raiz / "sw.js").is_file())

    def test_terminologia_nao_confirma_candidaturas_abertas(self):
        self.assertIn("oportunidades acompanhadas", self.html)
        self.assertIn("Referência de consulta manual", self.html)
        self.assertIn("Consulta manual", self.html)

    def test_verificador_esta_desativado_por_padrao(self):
        self.assertFalse(VERIFICADOR_ATIVO)


if __name__ == "__main__":
    unittest.main()
