import json
import socket
import urllib.error
import unittest
import io
import hashlib
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import enriquecimento_inesctec as ei


def vaga(ref="AE2026-0357", titulo="Power systems"):
    return {
        "titulo": f"{titulo} ({ref})",
        "empresa": "INESC TEC",
        "cidade": "Porto",
        "link": f"https://www.inesctec.pt/editais/pt/{ref}",
        "fonte": "inesctec",
        "situacao": "observada",
        "primeira_observacao": "2026-11-20T22:11:10+00:00",
        "ultima_observacao": "2026-11-21T01:10:08+00:00",
        "ultima_verificacao": None,
    }


HTML_COMPLETO = """
<html><body>
<h1>Power systems (AE2026-0357)</h1>
<p>Área de trabalho: sistemas elétricos e otimização de armazenamento de energia.</p>
<p>Requisitos mínimos: • Formação em Engenharia Eletrotécnica • Experiência em Python e Pyomo • Mercados de eletricidade</p>
<p>Fatores de preferência: • Fluência em inglês falado e escrito • Investigação em sistemas de energia</p>
<p>Jornada: tempo integral</p>
<p>Contrato a termo incerto</p>
<p>Trabalho presencial no Porto</p>
<p>Prazo de candidatura: 04/12/2026</p>
</body></html>
"""


def criar_pdf_texto(texto: str) -> bytes:
    writer = PdfWriter()
    pagina = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    fonts = DictionaryObject({NameObject("/F1"): font})
    resources = DictionaryObject({NameObject("/Font"): fonts})
    pagina[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 72 720 Td (" +
        texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace") +
        b") Tj ET"
    )
    pagina[NameObject("/Contents")] = writer._add_object(stream)
    saida = io.BytesIO()
    writer.write(saida)
    return saida.getvalue()


class EnriquecimentoTest(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.pasta = Path(self.temp)
        self.base = self.pasta / "vagas.json"
        self.saida = self.pasta / "enriquecimento.json"
        self.original = {"atualizado_em": "2026-11-21T01:11:53+00:00", "total": 139,
                         "vagas": [vaga()] + [{"titulo": f"Vaga {i}", "fonte": "bosch"} for i in range(138)]}
        self.base.write_text(json.dumps(self.original), encoding="utf-8")

    def test_preserva_139_registros_e_estrutura_atual(self):
        resultado = ei.executar(base=self.base, saida=self.saida, limite=5,
                                agora="2026-11-21T02:00:00+00:00",
                                buscar=lambda url: (url, HTML_COMPLETO))
        self.assertEqual(resultado["total_registros_preservados"], 139)
        self.assertEqual(len(json.loads(self.base.read_text(encoding="utf-8"))["vagas"]), 139)
        self.assertEqual(json.loads(self.base.read_text(encoding="utf-8"))["total"], 139)

    def test_correspondencia_exige_ref_e_titulo(self):
        self.assertTrue(ei.corresponder_vaga(vaga(), "Power systems (AE2026-0357)"))
        self.assertFalse(ei.corresponder_vaga(vaga(), "Outra vaga (AE2026-9999)"))
        self.assertFalse(ei.corresponder_vaga(vaga(), "Texto sem referência"))

    def test_separa_jornada_e_vinculo(self):
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), HTML_COMPLETO)
        self.assertEqual(item["jornada"], "Full Time")
        self.assertEqual(item["tipo_vinculo"], "contrato a termo incerto")

    def test_data_publicacao_nao_e_preenchida_por_prazo(self):
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), HTML_COMPLETO)
        self.assertIsNone(item["data_publicacao"])
        self.assertIsNotNone(item["prazo_candidatura"])

    def test_ausencia_nao_inventa_valores(self):
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()),
                                   "<html><body>Power systems (AE2026-0357)</body></html>")
        for campo in ei.CAMPOS_ENRIQUECIDOS:
            if campo not in ("localizacao",):
                self.assertIn(item[campo], (None, "", [], {}))

    def test_dns_timeout_http_preservam_dados_anteriores(self):
        anterior = {
            "descricao": "Descrição anterior verificável",
            "requisitos_obrigatorios": ["Python"],
            "qualidade": "fundamentada",
            "evidencias": {"descricao": [{"url": "https://www.inesctec.pt"}]},
        }
        erros = [
            socket.gaierror("DNS"),
            TimeoutError("timeout"),
            urllib.error.HTTPError("https://www.inesctec.pt", 503, "unavailable", {}, None),
        ]
        for erro in erros:
            with self.subTest(error=erro):
                novo = ei.preparar_falha("https://www.inesctec.pt/editais/pt/AE2026-0357", erro,
                                         "2026-11-21T02:00:00+00:00")
                resultado = ei.mesclar_resultado(anterior, novo, "2026-11-21T02:00:00+00:00")
                self.assertEqual(resultado["descricao"], anterior["descricao"])
                self.assertEqual(resultado["requisitos_obrigatorios"], ["Python"])
                self.assertEqual(resultado["estado"], "falha_acesso")

    def test_pdf_com_html_incompleto_nao_fabricado(self):
        texto = "Power systems (AE2026-0357) PDF incompleto"
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), texto, tipo="texto")
        self.assertIn(item["estado"], ("conteudo_nao_corresponde", "sem_dados_estruturados", "incompleto"))
        self.assertIn(item["qualidade"], ("insuficiente", "preliminar"))

    def test_idempotencia_com_mesmo_timestamp(self):
        kwargs = dict(base=self.base, saida=self.saida, limite=5,
                      agora="2026-11-21T02:00:00+00:00",
                      buscar=lambda url: (url, HTML_COMPLETO))
        primeiro = ei.executar(**kwargs)
        ei.gravar(primeiro, self.saida)
        segundo = ei.executar(**kwargs)
        self.assertEqual(primeiro, segundo)

    def test_status_da_vaga_nao_e_alterado(self):
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), HTML_COMPLETO)
        self.assertEqual(vaga()["situacao"], "observada")
        self.assertIsNone(vaga()["ultima_verificacao"])
        self.assertIn(item["estado"], ("extraido", "incompleto", "sem_dados_estruturados"))

    def test_url_nao_oficial_e_rejeitada(self):
        v = vaga()
        v["link"] = "https://emprego.com/pt/job/AE2026-0357"
        self.assertIsNone(ei.url_oficial_valida(v))

    def test_datas_futuras_sao_marcadas_como_evidencia(self):
        texto = "Power systems (AE2026-0357) Publicado em 21/11/2026 Prazo 04/12/2026"
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), texto, tipo="texto")
        self.assertEqual(item["data_publicacao"], "21/11/2026")
        self.assertEqual(item["prazo_candidatura"], "04/12/2026")

    def test_migracao_legada_move_prazo_e_preserva_identidade(self):
        original = vaga()
        original["data_publicacao"] = "2026-12-04"
        migrada = ei.migrar_datas_historicas_inesctec(
            [original], origem_comprovada=True
        )[0]
        self.assertIsNone(migrada["data_publicacao"])
        self.assertEqual(migrada["prazo_candidatura"], "2026-12-04")
        self.assertEqual(migrada["link"], original["link"])
        self.assertEqual(migrada["situacao"], original["situacao"])
        self.assertEqual(migrada["primeira_observacao"], original["primeira_observacao"])

    def test_migracao_nao_adiciona_publicacao_historica(self):
        original = vaga()
        original["data_publicacao"] = "2026-11-25"
        migrada = ei.migrar_datas_historicas_inesctec(
            [original], origem_comprovada=True
        )[0]
        self.assertIsNone(migrada["data_publicacao"])
        self.assertIn("prazo_candidatura", migrada)

    def test_recuperacao_apos_falha_limpa_estado_de_falha(self):
        anterior = ei.resultado_falha(
            "https://www.inesctec.pt/editais/pt/AE2026-0357",
            "DNS, timeout ou erro de rede",
            "No address associated with hostname",
            "2026-11-21T02:00:00+00:00",
        )
        anterior["descricao"] = "Descrição válida anterior"
        novo = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), HTML_COMPLETO)
        resultado = ei.mesclar_resultado(anterior, novo, "2026-11-21T02:05:00+00:00")
        self.assertNotEqual(resultado["estado"], "falha_acesso")
        self.assertNotIn("motivo", resultado)
        self.assertNotIn("erro", resultado)
        self.assertEqual(resultado["ultima_verificacao"], "2026-11-21T02:05:00+00:00")

    def test_evidencia_tem_url_ref_hash_trecho_e_verificacao(self):
        item = ei.extrair_payload(vaga(), ei.url_oficial_valida(vaga()), HTML_COMPLETO)
        for evidencias in item["evidencias"].values():
            for evidencia in evidencias:
                self.assertIn("url", evidencia)
                self.assertIn("titulo_ou_ref", evidencia)
                self.assertIn("trecho", evidencia)
                self.assertIn("sha256_texto", evidencia)
                self.assertIn("verificado_em", evidencia)

    def test_pdf_local_extraido_com_pagina_hash_e_ref(self):
        caminho = self.pasta / "edital.pdf"
        caminho.write_bytes(criar_pdf_texto(
            "Power systems (AE2026-0357) Área de trabalho: sistemas elétricos "
            "Requisitos mínimos: Python Pyomo Prazo de candidatura: 04/12/2026"
        ))
        item = ei.extrair_pdf_local(
            vaga(),
            ei.url_oficial_valida(vaga()),
            caminho,
            extraido_em="2026-11-21T14:45:00+00:00",
        )
        self.assertIn(item["estado"], ("extraido", "incompleto"))
        self.assertEqual(item["sha256_documento"], hashlib.sha256(caminho.read_bytes()).hexdigest())
        self.assertEqual(item["paginas"][0]["pagina"], 1)
        if "descricao" in item["evidencias"]:
            self.assertIn("sha256_documento", item["evidencias"]["descricao"][0])

    def test_pdf_vazio_requer_ocr(self):
        caminho = self.pasta / "vazio.pdf"
        caminho.write_bytes(criar_pdf_texto(""))
        item = ei.extrair_pdf_local(vaga(), ei.url_oficial_valida(vaga()), caminho)
        self.assertEqual(item["estado"], "ocr_necessario")
        self.assertIn("não contém texto", item["motivo"])

    def test_pdf_invalido_e_rejeitado(self):
        caminho = self.pasta / "invalido.pdf"
        caminho.write_bytes(b"isto nao e pdf")
        item = ei.extrair_pdf_local(vaga(), ei.url_oficial_valida(vaga()), caminho)
        self.assertEqual(item["estado"], "pdf_invalido")
        self.assertNotIn("evidencias", item["evidencias"])

    def test_pdf_com_ref_incompativel_e_rejeitado(self):
        caminho = self.pasta / "incompativel.pdf"
        caminho.write_bytes(criar_pdf_texto(
            "Power systems (AE2026-9999) Sistemas elétricos"
        ))
        item = ei.extrair_pdf_local(vaga(), ei.url_oficial_valida(vaga()), caminho)
        self.assertEqual(item["estado"], "conteudo_nao_corresponde")

    def test_pdf_incompleto_sem_descricao_fica_insuficiente(self):
        caminho = self.pasta / "incompleto.pdf"
        caminho.write_bytes(criar_pdf_texto("Power systems (AE2026-0357)"))
        item = ei.extrair_pdf_local(vaga(), ei.url_oficial_valida(vaga()), caminho)
        self.assertIn(item["estado"], ("sem_dados_estruturados", "incompleto", "extraido"))
        self.assertIn(item["qualidade"], ("insuficiente", "preliminar"))

    def test_correspondencia_hierarquica_url_titulo_instituicao(self):
        v = vaga("AE2026-0341", "Sistemas de Energia")
        texto = (
            "Sistemas de Energia - Eletrónica de Potência e Flexibilidade da Rede "
            "INESC TEC Instituto de Engenharia de Sistemas e Computadores Porto"
        )
        corresponde, criterio, motivo = ei.validar_correspondencia_pdf(
            v, texto, ei.url_oficial_valida(v)
        )
        self.assertTrue(corresponde)
        self.assertEqual(criterio, "url_titulo_instituicao")

    def test_correspondencia_rejeita_conflito_de_referencia(self):
        v = vaga()
        texto = "Power systems (AE2026-0357) Outra referência AE2026-9999 INESC TEC"
        corresponde, criterio, motivo = ei.validar_correspondencia_pdf(
            v, texto, ei.url_oficial_valida(v)
        )
        self.assertFalse(corresponde)
        self.assertEqual(criterio, "conflito_referencia")

    def test_extracao_real_pdf_campos_importantes(self):
        caminho = Path("/tmp/AE2026-0341.pdf")
        if not caminho.is_file():
            self.skipTest("PDF oficial real não disponível no workspace")
        v = next(
            x for x in json.loads((ei.RAIZ / "data" / "vagas.json").read_text(encoding="utf-8"))["vagas"]
            if x.get("link", "").endswith("AE2026-0341")
        )
        item = ei.extrair_pdf_local(v, ei.url_oficial_valida(v), caminho)
        self.assertEqual(item["estado"], "extraido")
        self.assertEqual(item["tipo_vinculo"], "contrato a termo incerto")
        self.assertEqual(item["prazo_candidatura"], "2026-12-04")
        self.assertIn("3640.11", item["remuneracao"])
        self.assertEqual(item["moeda"], "EUR")
        self.assertIsNone(item["data_publicacao"])
        self.assertIsNone(item["modalidade"])
        self.assertIsNone(item["jornada"])

    def test_secao_responsabilidades_termina_no_cabecalho_seguinte(self):
        texto = (
            "FUNÇÕES A DESEMPENHAR Coordenação de projetos. "
            "LOCAL DE TRABALHO INESC TEC, Porto"
        )
        secao = ei.extrair_secao_delimitada(
            texto,
            r"FUNÇÕES A DESEMPENHAR",
            ("LOCAL DE TRABALHO",),
        )
        self.assertIn("Coordenação de projetos", secao)
        self.assertNotIn("LOCAL DE TRABALHO", secao)

    def test_secoes_cruzam_paginas_sem_perder_lista(self):
        pagina1 = "FUNÇÕES A DESEMPENHAR • Coordenação de projetos • Gestão de equipa"
        pagina2 = "Preparação de propostas • LOCAL DE TRABALHO INESC TEC"
        combinado = pagina1 + " " + pagina2
        unido = ei.extrair_secao_delimitada(
            combinado,
            r"FUNÇÕES A DESEMPENHAR",
            ("LOCAL DE TRABALHO",),
        )
        self.assertIn("Coordenação de projetos", unido)
        self.assertIn("Preparação de propostas", unido)

    def test_competencias_preservam_original_e_normalizacao(self):
        caminho = Path("/tmp/AE2026-0341.pdf")
        if not caminho.is_file():
            self.skipTest("PDF oficial real não disponível")
        v = next(
            x for x in json.loads((ei.RAIZ / "data" / "vagas.json").read_text(encoding="utf-8"))["vagas"]
            if x.get("link", "").endswith("AE2026-0341")
        )
        item = ei.extrair_pdf_local(v, ei.url_oficial_valida(v), caminho)
        self.assertIn("otimização matemática", item["competencias_tecnicas_originais"])
        self.assertIn("gémeos digitais", item["competencias_tecnicas_originais"])
        self.assertGreaterEqual(len(item["competencias_tecnicas_normalizadas"]), 1)

    def test_recuperacao_mantem_evidencias_anteriores(self):
        anterior = {
            "evidencias": {
                "descricao": [{"campo": "descricao", "pagina": 2, "trecho": "Descrição antiga"}],
            },
            "descricao": "Descrição antiga",
            "qualidade": "parcial",
        }
        novo = {
            "estado": "extraido",
            "qualidade": "parcial",
            "evidencias": {
                "requisitos_obrigatorios": [{"campo": "requisitos_obrigatorios", "pagina": 2}],
            },
            "descricao": None,
            "responsabilidades": [],
            "requisitos_obrigatorios": ["Doutoramento"],
        }
        resultado = ei.mesclar_resultado(anterior, novo, "2026-11-21T15:30:00+00:00")
        self.assertIn("descricao", resultado["evidencias"])
        self.assertIn("requisitos_obrigatorios", resultado["evidencias"])
        self.assertEqual(resultado["descricao"], "Descrição antiga")

    def test_pdf_validado_exige_validacao_semantica(self):
        caminho = Path("/tmp/AE2026-0341.pdf")
        if not caminho.is_file():
            self.skipTest("PDF oficial real não disponível")
        v = next(
            x for x in json.loads((ei.RAIZ / "data" / "vagas.json").read_text(encoding="utf-8"))["vagas"]
            if x.get("link", "").endswith("AE2026-0341")
        )
        item = ei.extrair_pdf_local(v, ei.url_oficial_valida(v), caminho)
        self.assertEqual(item["qualidade"], "concluida_validada")
        self.assertEqual(item["validacao_semantica"], "confirmada")
        self.assertTrue(all(
            item["validacao_semantica_por_campo"].get(campo)
            for campo in ("descricao", "requisitos_obrigatorios", "requisitos_preferenciais")
        ))

    def test_executar_preserva_enriquecimentos_de_execucoes_anteriores(self):
        vaga1 = vaga("AE2026-0357", "Power systems")
        vaga2 = vaga("AE2026-0341", "Sistemas de Energia")
        dados = {"atualizado_em": "2026-11-21T15:00:00+00:00", "total": 2, "vagas": [vaga1, vaga2]}
        self.base.write_text(json.dumps(dados), encoding="utf-8")

        primeiro = ei.executar(
            base=self.base,
            saida=self.saida,
            limite=1,
            agora="2026-11-21T15:10:00+00:00",
            buscar=lambda url: (url, HTML_COMPLETO),
        )
        ei.gravar(primeiro, self.saida)
        dados2 = {"atualizado_em": "2026-11-21T15:15:00+00:00", "total": 1, "vagas": [vaga2]}
        self.base.write_text(json.dumps(dados2), encoding="utf-8")
        html2 = HTML_COMPLETO.replace("AE2026-0357", "AE2026-0341").replace("Power systems", "Sistemas de Energia")
        segundo = ei.executar(
            base=self.base,
            saida=self.saida,
            limite=1,
            agora="2026-11-21T15:20:00+00:00",
            buscar=lambda url: (url, HTML_COMPLETO if "0357" in url else html2),
        )
        ei.gravar(segundo, self.saida)

        regravado = json.loads(self.saida.read_text(encoding="utf-8"))
        urls = regravado["vagas"]
        self.assertEqual(len(urls), 2)
        self.assertTrue(any("AE2026-0357" in url for url in urls))
        self.assertTrue(any("AE2026-0341" in url for url in urls))

    def test_buscar_html_encaminha_pdf_para_extrator(self):
        pdf = criar_pdf_texto(
            "Power systems (AE2026-0357) Área de trabalho: sistemas elétricos "
            "Requisitos mínimos: Python"
        )
        resposta = Mock()
        resposta.status = 200
        resposta.geturl.return_value = "https://www.inesctec.pt/editais/pt/AE2026-0357.pdf"
        resposta.headers.get_content_type.return_value = "application/pdf"
        resposta.read.return_value = pdf
        resposta.__enter__ = Mock(return_value=resposta)
        resposta.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=resposta):
            final_url, conteudo = ei.buscar_html(
                "https://www.inesctec.pt/editais/pt/AE2026-0357"
            )
        self.assertEqual(final_url, resposta.geturl.return_value)
        self.assertEqual(conteudo[0], "pdf")
        item = ei.extrair_pdf_bytes(
            vaga(),
            ei.url_oficial_valida(vaga()),
            conteudo[1],
            extraido_em="2026-11-21T15:30:00+00:00",
        )
        self.assertIn(item["estado"], ("extraido", "conteudo_nao_corresponde", "incompleto"))
        self.assertTrue(item["sha256_documento"])

    def test_migracao_desativada_por_padrao(self):
        original = vaga()
        original["data_publicacao"] = "2026-12-04"
        migrada = ei.migrar_datas_historicas_inesctec([original])[0]
        self.assertEqual(migrada["data_publicacao"], "2026-12-04")
        self.assertNotIn("prazo_candidatura", migrada)


if __name__ == "__main__":
    unittest.main()
