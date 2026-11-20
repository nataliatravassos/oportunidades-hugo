import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sources import fct, fedex, inesctec
from sources.base import EstadoColeta, url_absoluta
from sources.playwright_utils import abrir_busca, coletar_paginas


class LinksTest(unittest.TestCase):
    def test_resolve_links_usando_a_url_final_e_preserva_parametros(self):
        base = "https://careers.fedex.com/pt/search/lista"
        casos = {
            "/job/id?job=123": "https://careers.fedex.com/job/id?job=123",
            "../job/id": "https://careers.fedex.com/pt/job/id",
            "//jobs.example.org/id": "https://jobs.example.org/id",
            "https://ats.example.org/apply?id=321": "https://ats.example.org/apply?id=321",
            "?job=123": "https://careers.fedex.com/pt/search/lista?job=123",
        }
        for href, esperado in casos.items():
            with self.subTest(href=href):
                self.assertEqual(url_absoluta(href, base), esperado)

    def test_rejeita_destinos_invalidos_mesmo_com_base(self):
        for href in (
            None, "", "#", "javascript:alert(1)", "mailto:a@b.pt", "http:sem-host",
            "https://", "https://jobs .example.com/a", "https://example.com:abc",
            "https://user:pass@example.com/", "https://[bad]/", "///vaga", "/job/a\nb",
            "https://bad<.example.org/",
        ):
            with self.subTest(href=href):
                self.assertIsNone(url_absoluta(href, "https://careers.fedex.com/jobs"))
        self.assertIsNone(url_absoluta("/job/id"))

    def test_fedex_usa_url_final_do_navegador(self):
        titulo = Mock()
        titulo.count.return_value = 1
        titulo.inner_text.return_value = "Industrial Engineer"
        titulo.get_attribute.return_value = "../job/123?job=1"
        opcional = Mock()
        opcional.count.return_value = 0
        item = Mock()
        item.locator.side_effect = {
            ".results-list__item-title--link": SimpleNamespace(first=titulo),
            ".results-list__item-street--label": SimpleNamespace(first=opcional),
            ".results-list__item-employment-type": SimpleNamespace(first=opcional),
            ".reference": SimpleNamespace(first=opcional),
        }.__getitem__
        itens = Mock()
        itens.count.return_value = 1
        itens.nth.return_value = item
        pagina = Mock(url="https://careers.fedex.com/pt/search/results")
        pagina.locator.return_value = itens

        self.assertEqual(
            fedex._extrair_pagina(pagina)[0]["link"],
            "https://careers.fedex.com/pt/job/123?job=1",
        )

    def test_fct_resolve_link_relativo_apos_redirecionamento(self):
        resposta = Mock(
            url="https://www.fct.pt/concursos/abertos/",
            text='<a href="../bolsa/"><span class="calendar__title">Bolsa</span></a>',
        )
        with patch.object(fct.requests, "get", return_value=resposta):
            resultado = fct.fetch()
        self.assertEqual(resultado.estado, EstadoColeta.COMPLETA)
        self.assertEqual(resultado.vagas[0]["link"], "https://www.fct.pt/concursos/bolsa/")


class ColetoresTest(unittest.TestCase):
    def test_inesctec_distingue_zero_explicito_de_resposta_incompativel(self):
        for payload, estado in (([], EstadoColeta.ZERO), ({}, EstadoColeta.FALHA)):
            with self.subTest(payload=payload):
                resposta = Mock(url=inesctec.API_URL)
                resposta.json.return_value = payload
                with patch.object(inesctec.requests, "get", return_value=resposta):
                    resultado = inesctec.fetch()
                self.assertEqual(resultado.estado, estado)
                self.assertTrue(resultado.motivo)

    def test_inesctec_lista_vazia_redirecionada_nao_confirma_zero(self):
        resposta = Mock(url="https://www.inesctec.pt/outro-endpoint")
        resposta.json.return_value = []
        with patch.object(inesctec.requests, "get", return_value=resposta):
            self.assertEqual(inesctec.fetch().estado, EstadoColeta.FALHA)

    def test_inesctec_mantem_os_editais_validos_de_resposta_parcial(self):
        resposta = Mock()
        resposta.json.return_value = [{"idEdital": "AE2026-0001"}, {"areaTrabalhoPT": "Sem ID"}]
        with patch.object(inesctec.requests, "get", return_value=resposta):
            resultado = inesctec.fetch()
        self.assertEqual(resultado.estado, EstadoColeta.PARCIAL)
        self.assertEqual(len(resultado.vagas), 1)

    def test_fct_html_sem_cartoes_nao_confirma_zero(self):
        resposta = Mock(url="https://www.fct.pt/concursos/", text="<html><p>Portal indisponível</p></html>")
        with patch.object(fct.requests, "get", return_value=resposta):
            self.assertEqual(fct.fetch().estado, EstadoColeta.FALHA)

    def test_pagina_http_com_erro_nao_parece_lista_vazia(self):
        pagina = Mock()
        pagina.goto.return_value = SimpleNamespace(ok=False, status=503)
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            abrir_busca(pagina, "https://example.org")


class PaginacaoTest(unittest.TestCase):
    def setUp(self):
        self.controle = Mock()
        self.controle.count.return_value = 1
        self.controle.is_disabled.return_value = False
        self.link = "https://example.org/jobs/1"
        self.vaga = {"link": self.link}

    def test_timeout_na_segunda_pagina_retem_a_primeira(self):
        with (
            patch("sources.playwright_utils.links_dos_cartoes", return_value=[self.link]),
            patch("sources.playwright_utils.esperar_resultados", side_effect=TimeoutError),
        ):
            resultado = coletar_paginas(Mock(), ".card", lambda _: [self.vaga], lambda _: self.controle, 10)
        self.assertEqual(resultado.estado, EstadoColeta.PARCIAL)
        self.assertEqual(resultado.vagas, [self.vaga])
        self.assertEqual(resultado.paginas, 1)

    def test_pagina_repetida_e_parcial(self):
        with (
            patch("sources.playwright_utils.links_dos_cartoes", return_value=[self.link]),
            patch("sources.playwright_utils.esperar_resultados"),
        ):
            resultado = coletar_paginas(Mock(), ".card", lambda _: [self.vaga], lambda _: self.controle, 10)
        self.assertEqual(resultado.estado, EstadoColeta.PARCIAL)
        self.assertIn("repetida", resultado.motivo)
        self.assertEqual(resultado.vagas, [self.vaga])

    def test_limite_com_navegacao_restante_e_parcial(self):
        with patch("sources.playwright_utils.links_dos_cartoes", return_value=[self.link]):
            resultado = coletar_paginas(Mock(), ".card", lambda _: [self.vaga], lambda _: self.controle, 1)
        self.assertEqual(resultado.estado, EstadoColeta.PARCIAL)
        self.assertIn("Limite", resultado.motivo)

    def test_fim_da_paginacao_so_e_sucesso_quando_extrai_todos_os_cartoes(self):
        self.controle.count.return_value = 0
        for links, estado in (
            ([self.link], EstadoColeta.COMPLETA),
            ([self.link, "https://example.org/jobs/2"], EstadoColeta.PARCIAL),
        ):
            with self.subTest(links=links):
                with patch("sources.playwright_utils.links_dos_cartoes", return_value=links):
                    resultado = coletar_paginas(Mock(), ".card", lambda _: [self.vaga], lambda _: self.controle, 10)
                self.assertEqual(resultado.estado, estado)


if __name__ == "__main__":
    unittest.main()
