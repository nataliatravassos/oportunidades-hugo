# Oportunidades — Porto e região

Programa que busca, todo dia automaticamente, vagas de emprego e editais/concursos
de pesquisa na região do Porto, juntando várias fontes numa lista só:

- **Empresas:** Bosch, FedEx, DHL, Sonae, IKEA, Siemens, Nestlé, Microsoft
- **Institutos de pesquisa:** INESC TEC, FCT (concursos nacionais tipo CEEC),
  além de uma lista com outros institutos do Porto que vale a pena olhar
  manualmente de vez em quando (INEGI, Instituto de Telecomunicações,
  Fraunhofer Portugal AICOS, CEiiA, ISR-Porto)

O resultado fica salvo em `data/vagas.json` (dados completos) e `data/vagas.md`
(tabela legível, já separada em "escritório", "não dá pra saber" e
"operacional" pela palavra-chave do cargo).

## Como colocar isso no seu GitHub

1. Crie um repositório novo no GitHub (pode ser privado ou público, tanto faz).
2. Suba todos esses arquivos pra lá (pela interface do GitHub mesmo, arrastando
   os arquivos, ou por `git push` se preferir usar o terminal).
3. Pronto — não precisa configurar mais nada. O workflow em
   `.github/workflows/daily.yml` já roda sozinho todo dia às 7h (UTC).
4. Pra rodar uma vez na hora, sem esperar o dia seguinte: vá na aba **Actions**
   do repositório → clique em **"Buscar vagas diariamente"** → **"Run workflow"**.
5. Depois que rodar, os arquivos `data/vagas.json` e `data/vagas.md` aparecem
   atualizados no repositório — o próprio GitHub Actions commita o resultado
   automaticamente.

Não precisa de nenhuma senha, chave de API ou configuração extra: o GitHub já
dá ao workflow a permissão que ele precisa pra salvar o resultado.

## Rodando no seu computador (opcional, só pra testar)

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

Pra testar só uma fonte específica (útil se uma empresa mudou o site e o
scraper daquela empresa quebrou):

```bash
python -m sources.bosch
```

## Sobre a pergunta "dá pra ser só um Artifact do Claude, sem GitHub?"

Não totalmente — um Artifact roda só quando alguém abre a página (ele não tem
como "acordar sozinho" uma vez por dia). Por isso a busca em si (abrir cada
site, aplicar filtro, etc.) precisa rodar em algum lugar que funcione sem
ninguém estar olhando — e é exatamente isso que o GitHub Actions faz aqui.

Mas depois que esse projeto estiver rodando no seu GitHub, dá sim pra pedir
pro Claude montar um Artifact (um painel bonitinho) que lê o `data/vagas.json`
direto do seu repositório toda vez que você abrir — assim você não precisa
nem entrar no GitHub pra ver as vagas, só abrir o Artifact aqui no Claude. É
só pedir depois que o repositório estiver no ar.

## Limitações e manutenção

- **Sites mudam.** Cada `sources/<empresa>.py` depende da estrutura atual do
  site daquela empresa. Se um dia parar de trazer resultado, o site
  provavelmente mudou de layout — é só pedir pro Claude investigar e corrigir
  aquele arquivo específico (não precisa mexer nos outros).
- **`outros_institutos.py` não busca vagas de verdade ainda** — só lembra de
  conferir manualmente os institutos listados. Dá pra transformar num scraper
  de verdade depois (o arquivo já tem um guia de como fazer isso).
- **A classificação "escritório/operacional" é só uma estimativa** baseada em
  palavras do título do cargo — não é perfeita, serve só pra ordenar a lista
  e facilitar a leitura.
- **Uma fonte quebrada não derruba as outras:** se um site falhar
  (fora do ar, mudou de layout, etc.), o programa loga o erro e continua
  buscando nas outras fontes normalmente.

## Estrutura dos arquivos

```
main.py                 → junta tudo, filtra por região e salva o resultado
config.py                → lista de fontes ativas + regra de "é região do Porto?"
sources/base.py          → formato comum de cada vaga + classificação por palavra-chave
sources/*.py              → um arquivo por fonte (empresa ou instituto)
data/vagas.json           → resultado em dados (gerado automaticamente)
data/vagas.md              → resultado em tabela legível (gerado automaticamente)
.github/workflows/daily.yml → agendamento que roda tudo isso todo dia
```
