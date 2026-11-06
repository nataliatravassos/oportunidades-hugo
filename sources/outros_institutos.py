"""
Outros institutos de investigação com atuação no Porto que podem ser boas
fontes de bolsas/vagas para o perfil do Hugo (matemática + engenharia
elétrica + programação). Eu (Claude) escolhi esses nomes por conhecimento
geral da área, mas NÃO validei manualmente a página de cada um durante a
sessão em que este projeto foi criado — diferente do INESC TEC e da FCT,
que foram checados ao vivo.

Por isso, em vez de arriscar um scraper que já nasce quebrado (e falha
silenciosamente todo dia), deixei aqui só a lista com o nome, a área de
atuação e um link de partida para cada instituto. O código real de busca
fica pendente — veja o TODO de cada função.

Como preencher um TODO:
 1. Abra o link em "página de partida" no navegador.
 2. Procure o menu "Careers" / "Trabalhe Connosco" / "Oportunidades".
 3. Veja se a lista de vagas é HTML estático (dá pra usar requests +
    BeautifulSoup, como em fct.py) ou se é carregada via JavaScript
    (nesse caso, inspecione a aba "Network" do DevTools procurando uma
    chamada a algum endpoint JSON, como fizemos com o INESC TEC; se não
    achar nenhuma, use Playwright, como nos scrapers de empresas).
 4. Implemente a função seguindo o mesmo formato das outras fontes:
    devolva uma lista de dicts criados com `make_vaga(...)`.
"""

from __future__ import annotations

from .base import make_vaga

# Institutos sugeridos, com uma descrição rápida de por que podem interessar
# ao Hugo. Cada um vira uma "vaga" avisando que ainda não há busca
# automática, só pra lembrar que vale a pena olhar manualmente de vez em
# quando até alguém (você, eu numa próxima sessão, ou outro colaborador)
# implementar o scraper de verdade.
INSTITUTOS_SUGERIDOS = [
    {
        "nome": "INEGI — Instituto de Ciência e Inovação em Engenharia Mecânica e Engenharia Industrial",
        "motivo": "Instituto de engenharia associado à FEUP, no Porto; projetos de automação, energia e dados.",
        "pagina_partida": "https://www.inegi.pt/pt/carreiras/",
    },
    {
        "nome": "IT — Instituto de Telecomunicações (polo do Porto)",
        "motivo": "Pesquisa em telecomunicações e sistemas elétricos/eletrónicos; forte interseção com Engenharia Elétrica.",
        "pagina_partida": "https://www.it.pt",
    },
    {
        "nome": "Fraunhofer Portugal AICOS",
        "motivo": "Centro de investigação em Inteligência Artificial e Ciência de Dados, sediado no Porto.",
        "pagina_partida": "https://www.fraunhofer.pt",
    },
    {
        "nome": "CEiiA — Centro de Engenharia e Desenvolvimento de Produto",
        "motivo": "Centro de engenharia (mobilidade, indústria, espaço) com polo em Matosinhos.",
        "pagina_partida": "https://www.ceiia.com/carreiras",
    },
    {
        "nome": "ISR-Porto — Instituto de Sistemas e Robótica, polo do Porto (FEUP)",
        "motivo": "Robótica e sistemas, ligado à Faculdade de Engenharia da Universidade do Porto.",
        "pagina_partida": "https://www.isr.uc.pt",
    },
]


def fetch() -> list[dict]:
    vagas = []
    for inst in INSTITUTOS_SUGERIDOS:
        vagas.append(
            make_vaga(
                titulo=f"[verificar manualmente] Oportunidades em {inst['nome']}",
                empresa=inst["nome"],
                cidade="Porto (verificar)",
                link=inst["pagina_partida"],
                fonte="outros_institutos",
                categoria=inst["motivo"],
            )
        )
    return vagas


if __name__ == "__main__":
    import json

    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
