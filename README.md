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
5. O GitHub Actions commita o resultado automaticamente na branch padrão.
   A data de `data/vagas.json` e `data/vagas.md` avança quando os dados mudam.
   `data/coleta.json` regista a última tentativa e o resultado por fonte.

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

A suíte automatizada usa respostas simuladas e dispensa acesso aos portais
e instalação do navegador.

```bash
python -m unittest discover -s tests -v
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
- Uma falha preserva as vagas da fonte. Uma coleta parcial pode acrescentar
  vagas. As vagas ausentes numa coleta aproveitável, inclusive quando a
  fonte confirma zero, continuam visíveis como «por confirmar», com a data
  em que foram vistas pela última vez. O reaparecimento retira essa marca.
  Se todas as fontes automáticas falharem, só o diagnóstico é publicado e o
  workflow fica com estado de falha.
- A API do INESC TEC permite validar uma lista integral ou um zero. O IKEA
  pode confirmar a cobertura do raio de Porto quando o total anunciado
  coincide com todos os cartões válidos da página. Para
  Bosch, DHL, FedEx, FCT, Microsoft, Nestlé, Siemens e Sonae, a
  extração aproveitável é parcial enquanto o layout, os filtros ou a
  paginação não demonstrarem a cobertura total. A lista dos outros
  institutos é estática e não conta como coleta automática.
- Caminhos legados da FedEx que correspondam às rotas observadas no portal
  oficial são normalizados. Destinos fora desse padrão ficam sem link
  clicável até uma nova observação com um destino reconhecido. A data de
  observação refere-se à listagem e pode avançar sem alterar o carimbo do
  conteúdo. Isso não comprova que a candidatura continua aberta.
- Os diagnósticos incluem o recorte consultado e, quando disponível, a
  contagem anunciada pelo portal. Uma vaga da Microsoft fora da região
  entra como remota apenas quando o cartão inclui Portugal e o anúncio
  confirma zero dias de escritório com indicação explícita de trabalho
  remoto. O aplicativo identifica `Europe/Lisbon` no cabeçalho e nos cartões.

## Estrutura dos arquivos

```
main.py                 → junta tudo, filtra por região e salva o resultado
config.py                → lista de fontes ativas + regra de "é região do Porto?"
sources/base.py          → formato comum de cada vaga + classificação por palavra-chave
sources/*.py              → um arquivo por fonte (empresa ou instituto)
data/vagas.json           → resultado em dados (gerado automaticamente)
data/vagas.md              → resultado em tabela legível (gerado automaticamente)
data/coleta.json          → diagnóstico da tentativa mais recente (gerado automaticamente)
.github/workflows/daily.yml → agendamento que roda tudo isso todo dia
```
