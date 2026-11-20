import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import main
from config import eh_regiao_porto, remoto_elegivel
from publicacao import carregar_base, publicar, validar_vaga
from sources import bosch, dhl, microsoft, nestle, siemens, sonae
from sources.base import EstadoColeta, ResultadoColeta, make_vaga, url_absoluta
from sources.fedex_links import url_vaga_fedex
from sources.playwright_utils import ErroNavegacao


FIXTURES = Path(__file__).parent / "fixtures"


def ler(nome):
    return (FIXTURES / nome).read_text(encoding="utf-8")


class BoschTest(unittest.TestCase):
    def test_cartoes_reais_com_campos_separados_e_data_iso(self):
        aveiro = bosch.extrair_cartao(ler("bosch-aveiro.html"), bosch.URL)
        lisboa = bosch.extrair_cartao(ler("bosch-lisboa.html"), bosch.URL)
        self.assertEqual(aveiro["titulo"], "SAP Process Expert Source to Pay (f/m/div.)")
        self.assertEqual(aveiro["cidade"], "Aveiro")
        self.assertEqual(aveiro["data_publicacao"], "2026-11-20")
        self.assertEqual(aveiro["modalidade"], "hibrido")
        self.assertTrue(aveiro["link"].startswith("https://jobs.bosch.com/en/job/"))
        self.assertTrue(eh_regiao_porto(aveiro["cidade"]))
        self.assertFalse(eh_regiao_porto(lisboa["cidade"]))

    def test_rotulos_podem_mudar_e_data_ruim_nao_vira_publicacao(self):
        html = ler("bosch-aveiro.html").replace("Bosch Location", "Changed label").replace("11/20/2026", "not a date")
        vaga = bosch.extrair_cartao(html, bosch.URL)
        self.assertEqual(vaga["cidade"], "Aveiro")
        self.assertIsNone(vaga["data_publicacao"])
        self.assertIsNone(bosch.extrair_cartao(html.replace('title="locator"', 'title="bad"'), bosch.URL))
        self.assertIsNone(bosch.extrair_cartao(html.replace("jobs.bosch.com", "example.org"), bosch.URL))

    def test_paginacao_limitada_mantem_cartao_e_continua_parcial(self):
        page = Mock(url=bosch.URL)
        page.get_by_text.return_value.first.all_text_contents.return_value = ["Your results: 228 results"]
        botao = page.locator.return_value.first
        botao.count.return_value = 1
        botao.is_visible.return_value = True
        botao.is_disabled.return_value = False
        cartao = bosch.extrair_cartao(ler("bosch-aveiro.html"), bosch.URL)
        contexto = Mock()
        contexto.__enter__ = Mock(return_value=page)
        contexto.__exit__ = Mock(return_value=None)
        with (
            patch.object(bosch, "nova_pagina", return_value=contexto),
            patch.object(bosch, "abrir_busca"),
            patch.object(bosch, "clicar_se_existir"),
            patch.object(bosch, "links_dos_cartoes", return_value=[cartao["link"]]),
            patch.object(bosch, "_extrair_pagina", return_value=[cartao]),
            patch.object(bosch, "esperar_resultados", side_effect=[None, TimeoutError("parou de crescer")]),
        ):
            resultado = bosch.fetch()
        self.assertEqual(resultado.estado, EstadoColeta.PARCIAL)
        self.assertEqual(resultado.vagas, [cartao])
        self.assertEqual(resultado.consulta["total_anunciado"], 228)
        self.assertIn("parou de crescer", resultado.motivo)


class FedexTest(unittest.TestCase):
    def test_formatos_reais_continuam_sujeitos_ao_filtro_regional(self):
        cartoes = json.loads(ler("fedex-cartoes.json"))
        for i, cartao in enumerate(cartoes):
            with self.subTest(ref=cartao["ref"]):
                href, titulo, estilo = cartao["links"][0]
                self.assertEqual(estilo, "results-list__item-title--link")
                self.assertEqual(href, cartao["links"][1][0])
                vaga = make_vaga(titulo=titulo, link=url_absoluta(href, "https://careers.fedex.com"),
                                 cidade=cartao["local"], fonte="fedex", empresa="FedEx", categoria=cartao["ref"])
                self.assertTrue(validar_vaga(vaga)["link"].startswith("https://careers.fedex.com/"))
                self.assertEqual(eh_regiao_porto(vaga["cidade"]), i == 0)

    def test_referencia_textual_precisa_coincidir_com_a_rota(self):
        rota = "https://careers.fedex.com/database-advisor/job/P25-335348-6"
        self.assertEqual(url_vaga_fedex(rota, referencia="P25-335348-6"), rota)
        self.assertIsNone(url_vaga_fedex(rota))
        self.assertIsNone(url_vaga_fedex(rota, referencia="P25-335348-7"))
        self.assertIsNone(url_vaga_fedex(rota.replace("fedex.com", "example.org"), referencia="P25-335348-6"))


class MicrosoftTest(unittest.TestCase):
    def test_amostra_real_nacional_com_work_site_remoto_e_elegivel(self):
        vaga = microsoft.extrair_cartao(ler("microsoft-cartao.html"), "https://apply.careers.microsoft.com/careers")
        self.assertEqual(vaga["cidade"], "Portugal, Multiple Locations, Multiple Locations + 4 more")
        self.assertEqual(vaga["modalidade"], "desconhecido")
        self.assertFalse(remoto_elegivel(vaga))
        vaga.update(microsoft.modalidade_do_anuncio(ler("microsoft-work-site.html"), vaga["cidade"]))
        self.assertTrue(remoto_elegivel(validar_vaga(vaga)))

    def test_hibrido_presencial_e_texto_generico_nao_implicam_remoto(self):
        for evid, modo in (("3 days / week in-office", "hibrido"), ("Fully on-site", "presencial"),
                           ("Remote during training", "desconhecido"), ("0 days / week in-office", "desconhecido")):
            with self.subTest(modo=modo):
                html = f"<dl><dt>Work site</dt><dd>{evid}</dd></dl>"
                vaga = microsoft.modalidade_do_anuncio(html, "Portugal")
                self.assertEqual(vaga["modalidade"], modo)
                self.assertFalse(remoto_elegivel(vaga))
        remoto_externo = microsoft.modalidade_do_anuncio(ler("microsoft-work-site.html"), "Germany, Berlin")
        self.assertEqual(remoto_externo["modalidade"], "remoto")
        self.assertFalse(remoto_elegivel(remoto_externo))

    def test_falha_e_coleta_parcial_preservam_os_registos_publicados(self):
        with TemporaryDirectory() as temp:
            pasta = Path(temp)
            base = json.loads(ler("fedex-cartoes.json"))[0]
            anterior_fedex = validar_vaga(make_vaga(
                titulo=base["links"][0][1], empresa="FedEx", cidade=base["local"],
                link=url_absoluta(base["links"][0][0], "https://careers.fedex.com"),
                fonte="fedex", categoria=base["ref"],
            ))
            publicar(pasta, {"atualizado_em": "2026-11-20T15:51:20+00:00", "total": 1,
                             "vagas": [anterior_fedex]}, {})
            anterior, anteriores = carregar_base(pasta)
            vaga = microsoft.extrair_cartao(ler("microsoft-cartao.html"), "https://apply.careers.microsoft.com/careers")
            vaga.update(microsoft.modalidade_do_anuncio(ler("microsoft-work-site.html"), vaga["cidade"]))
            hibrida = {**vaga, "link": vaga["link"] + "?fixture=hibrida", "modalidade": "hibrido"}
            respostas = {
                "fedex": ResultadoColeta(EstadoColeta.FALHA, motivo="timeout simulado"),
                "microsoft": ResultadoColeta(EstadoColeta.PARCIAL, [vaga, hibrida], "cobertura limitada",
                                             consulta={"escopo": "Portugal"}),
            }
            with (
                patch.object(main, "PASTA_DADOS", pasta),
                patch.object(main, "FONTES", list(respostas)),
                patch.object(main, "rodar_fonte", side_effect=respostas.__getitem__),
                patch.object(main, "logger"),
            ):
                self.assertEqual(main.main(), 0)
            dados, registos = carregar_base(pasta)
            self.assertEqual(dados["total"], anterior["total"] + 1)
            self.assertTrue(all(v in registos for v in anteriores))
            saude = json.loads((pasta / "coleta.json").read_text(encoding="utf-8"))["fontes"]["microsoft"]
            self.assertEqual((saude["extraidas"], saude["remotas_elegiveis"], saude["fora_do_recorte"]), (2, 1, 1))
            self.assertEqual(saude["consulta"]["escopo"], "Portugal")


class FiltrosTest(unittest.TestCase):
    def test_dhl_aceita_variacoes_portuguesas_e_rejeita_homonimos(self):
        self.assertTrue(dhl.local_dhl_valido("Porto, Portugal"))
        self.assertTrue(dhl.local_dhl_valido("Maia, Porto, PT"))
        for local in ("Porto", "Porto Alegre, Brazil", "Porto, Italy", "Lisboa, Portugal"):
            self.assertFalse(dhl.local_dhl_valido(local))

    def test_siemens_precisa_dos_valores_confirmados(self):
        page = Mock(url="https://jobs.siemens.com/pt_PT/externaljobs/SearchJobs?country%5B%5D=812097&district%5B%5D=42")
        page.locator.return_value.evaluate_all.return_value = []
        self.assertTrue(siemens._filtros_aplicados(page, [("country[]", "812097"), ("district[]", "42")]))
        self.assertFalse(siemens._filtros_aplicados(page, [("country[]", "812097"), ("district[]", "99")]))

    def test_dhl_confirma_url_mesmo_que_o_campo_seja_limpo(self):
        rota = "https://careers.dhl.com/global/en/search-results"
        self.assertTrue(dhl.filtro_confirmado(rota + "?p=sample&location=Porto,%20Portugal", "Porto, Portugal", ""))
        self.assertFalse(dhl.filtro_confirmado(rota + "?location=Porto,%20Portugal", "Porto, Portugal", ""))
        self.assertFalse(dhl.filtro_confirmado(rota + "?p=sample&location=Porto%20Alegre,%20Brazil", "Porto, Portugal", ""))

    def test_siemens_aceita_serializacao_do_portal(self):
        page = Mock(url="https://jobs.siemens.com/pt_PT/externaljobs/SearchJobs/?42414=%5B812097%5D")
        page.locator.return_value.evaluate_all.return_value = []
        self.assertTrue(siemens._filtros_aplicados(page, [("42414[]", "812097")]))
        self.assertFalse(siemens._filtros_aplicados(page, [("42414[]", "81209")]))

    def test_sonae_descarta_destino_de_cartao_desatualizado_apos_filtrar(self):
        caminho = "/pt/talento/oportunidades/operador-a-de-loja-part-time-18h00-22h00-945355"
        url = sonae._link_anuncio(caminho, sonae.URL)
        self.assertTrue(sonae._titulo_corresponde("OPERADOR/A DE LOJA | PART-TIME (18h00 - 22h00)", url))
        self.assertFalse(sonae._titulo_corresponde("VENDEDOR/A DE LOJA", url))
        self.assertIsNone(sonae._link_anuncio("https://example.org" + caminho, sonae.URL))

    def test_nestle_403_nao_tenta_contornar_nem_publica_zero(self):
        contexto = Mock()
        contexto.__enter__ = Mock(return_value=Mock(url=nestle.URL))
        contexto.__exit__ = Mock(return_value=None)
        with patch.object(nestle, "nova_pagina", return_value=contexto), patch.object(
            nestle, "abrir_busca", side_effect=ErroNavegacao(403),
        ) as abrir:
            resultado = nestle.fetch()
        abrir.assert_called_once()
        self.assertEqual(resultado.estado, EstadoColeta.FALHA)
        self.assertIn("HTTP 403", resultado.motivo)
        self.assertEqual(resultado.consulta["consulta_manual"], nestle.URL_PORTUGAL)
