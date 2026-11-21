import datetime as dt
import json
import subprocess
import unittest
from pathlib import Path

import compatibilidade


HOJE = dt.date(2026, 11, 21)


def vaga(**campos):
    base = {
        "titulo": "Investigador em Sistemas de Energia",
        "empresa": "INESC TEC",
        "cidade": "Porto",
        "fonte": "inesctec",
        "link": "https://www.inesctec.pt/editais/pt/AE2026-0341",
        "situacao": "observada",
        "ultima_verificacao": None,
        "descricao": "Otimização matemática de sistemas elétricos",
    }
    base.update(campos)
    return base


class PerfilTest(unittest.TestCase):
    def setUp(self):
        self.perfil = compatibilidade.carregar_perfil()

    def test_perfil_configurado_nao_inventa_certificacao(self):
        ingles = self.perfil["idiomas"]["ingles"]
        self.assertEqual(ingles["certificacao"], "desconhecida")
        self.assertIsNone(self.perfil["preferencias"]["salario_minimo"])

    def test_alta_afinidade_com_impedimento_obrigatorio(self):
        v = vaga(requisitos_obrigatorios=[
            "Doutorados há mais de 5 anos, com experiência pós-doutoral",
        ])
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["classificacao"], "baixa_compatibilidade")
        self.assertIn("Doutorado", " ".join(r["impedimentos_obrigatorios"]))
        self.assertEqual(r["afinidade"], "alta")

    def test_alta_afinidade_com_elegibilidade_desconhecida(self):
        v = vaga(requisitos_obrigatorios=None, requisitos_preferenciais=None)
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["classificacao"], "precisa_verificar")
        self.assertIn("Requisitos obrigatórios", r["informacoes_desconhecidas"])

    def test_vaga_sem_informacoes_fica_precisa_verificar(self):
        v = vaga(
            titulo="Vaga técnica",
            descricao=None,
            cidade=None,
            prazo_candidatura=None,
            requisitos_obrigatorios=None,
        )
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["classificacao"], "precisa_verificar")
        self.assertIn("Localização", r["informacoes_desconhecidas"])

    def test_requisito_preferencial_nao_atendido_nao_e_impedimento(self):
        v = vaga(requisitos_obrigatorios=["Doutorado"], requisitos_preferenciais=[
            "Coordenação de projetos internacionais",
        ])
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertFalse(r["impedimentos_obrigatorios"])
        self.assertEqual(r["requisitos_preferenciais"], ["Coordenação de projetos internacionais"])

    def test_localizacao_e_modalidade_desconhecidas(self):
        v = vaga(cidade=None, modalidade=None)
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["localizacao"], "desconhecida")
        self.assertIn("Localização", r["informacoes_desconhecidas"])

    def test_prazo_vencido_resulta_em_baixa_compatibilidade(self):
        v = vaga(prazo_candidatura="2026-11-20")
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["prazo"], "vencido")
        self.assertEqual(r["classificacao"], "baixa_compatibilidade")

    def test_prazo_vigente_e_hibrido_remoto(self):
        v = vaga(prazo_candidatura="2026-12-04", modalidade="hibrido")
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["prazo"], "vigente")
        self.assertEqual(r["localizacao"], "favoravel")

    def test_139_registros_preservados_e_estados_inalterados(self):
        caminho = Path(__file__).resolve().parents[1] / "data" / "vagas.json"
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        estados = {v.get("situacao", "observada") for v in dados["vagas"]}
        ids = [v.get("link") for v in dados["vagas"]]
        avaliacoes = [compatibilidade.avaliar_vaga(v, self.perfil, HOJE) for v in dados["vagas"]]
        self.assertEqual(dados["total"], 139)
        self.assertEqual(len(dados["vagas"]), 139)
        self.assertEqual(len(avaliacoes), 139)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(estados.issubset({"observada", "por_confirmar", "encerrada"}))

    def test_exemplo_ae2026_0341_e_alta_afinidade_baixa_elegibilidade(self):
        v = vaga(
            titulo="Sistemas de Energia - Eletrónica de Potência",
            descricao="Otimização matemática de sistemas elétricos e gémeos digitais",
            requisitos_obrigatorios=[
                "Doutorados há mais de 5 anos",
                "Experiência pós-doutoral",
            ],
            requisitos_preferenciais=["Otimização da operação de redes elétricas"],
            prazo_candidatura="2026-12-04",
            modalidade="presencial",
        )
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["afinidade"], "alta")
        self.assertEqual(r["classificacao"], "baixa_compatibilidade")
        self.assertTrue(r["impedimentos_obrigatorios"])

    def test_reproducibilidade_da_avaliacao(self):
        v = vaga(requisitos_obrigatorios=["Doutorado"], prazo_candidatura="2026-12-04")
        r1 = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        r2 = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r1, r2)

    def test_logica_javascript_retorna_mesma_classificacao(self):
        script = """
const c = require("./compatibilidade.js");
const perfil = {
  competencias_confirmadas: ["otimizacao matematica", "modelagem matematica e computacional", "sistemas eletricos e energeticos"],
  preferencias: { localidades_prioritarias: ["porto", "matosinhos", "gaia", "maia"] }
};
const vaga = {
  titulo: "Investigador em Sistemas de Energia",
  descricao: "Otimização matemática de sistemas elétricos",
  cidade: "Porto",
  requisitos_obrigatorios: ["Doutorados há mais de 5 anos"],
  prazo_candidatura: "2026-12-04"
};
process.stdout.write(c.avaliar(vaga, perfil, "2026-11-21").classificacao);
"""
        resultado = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(resultado.stdout, "baixa_compatibilidade")

    def test_texto_generico_nao_cria_baixa_afinidade(self):
        v = vaga(titulo="Vaga técnica", descricao="Oportunidade técnica")
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        self.assertEqual(r["afinidade"], "insuficiente")

    def test_impedimento_tem_contexto_do_doutorado(self):
        v = vaga(requisitos_obrigatorios=["Doutorados há mais de 5 anos"])
        r = compatibilidade.avaliar_vaga(v, self.perfil, HOJE)
        texto = " ".join(r["impedimentos_obrigatorios"])
        self.assertIn("Doutorado", texto)
        self.assertIn("2023", texto)


if __name__ == "__main__":
    unittest.main()
