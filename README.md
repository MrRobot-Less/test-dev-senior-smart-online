# smart-online-automation

## Como executar

```bash
cp .env.example .env
docker compose up -d db
uv sync
uv run playwright install chromium
uv run pytest
uv run python -m smart_online_automation seed
uv run python -m smart_online_automation run
```

Por padrão o navegador abre visilmente, para não abrir automaticamente use a flag --handless

```bash
uv run python -m smart_online_automation run --headless
```

Para ver as chaves e o status atual no banco, formatado:

```bash
uv run python -m smart_online_automation review
```

Para zerar o banco e voltar ao estado inicial (recria a tabela e carrega as chaves como pendentes):

```bash
uv run python -m smart_online_automation reset
```

O `run` processa apenas chaves `PENDENTE` ou `ERRO` (reprocessamento seletivo). Para
reprocessar chaves específicas ou todas:

```bash
uv run python -m smart_online_automation run --key 33260829612882000128550040000113801131657747
uv run python -m smart_online_automation run --key <chave1> --key <chave2>
uv run python -m smart_online_automation run --all
```

Chaves informadas em `--key` que ainda não existem no banco são cadastradas como pendentes automaticamente.

## Como funciona a consulta

O robô preenche a chave, seleciona "TODOS" no filtro Débitos (em Dados Complementares) e pesquisa. Na página seguinte, quando carregada, o resultado é decidido pelo valor monetário ao lado de "Total a Recolher": `R$ 0,00` -> `SEM_DEBITO`; valor maior que zero -> `DEBITO` com esse valor. Se o portal responder com o diálogo de informação em vez de navegar, o diálogo é classificado da mesma forma. Cada consulta recarrega a página de busca

### Docker Compose (PostgreSQL)

```bash
cp .env.example .env
docker compose up --build
docker compose exec db psql -U automation -d automation
```

### Seed

O script `sql/schema.sql` cria a tabela e insere as 7 chaves do teste:

```bash
docker compose exec -T db psql -U automation -d automation < sql/schema.sql
```

## Análise dos resultados (SQL)

```sql
-- Status geral
SELECT chave, status, valor_pagar, consultada_em
FROM consultas_nfe
ORDER BY chave;

-- Chaves com débito e valor a pagar
SELECT chave, valor_pagar, consultada_em
FROM consultas_nfe
WHERE status = 'DEBITO';

-- Chaves com erro
SELECT chave, detalhes, tentativas
FROM consultas_nfe
WHERE status = 'ERRO';

-- Resumo por status
SELECT status, count(*)
FROM consultas_nfe
GROUP BY status
ORDER BY status;
```

para ver um resumo rode com o comando `review`


para testar os retries um exemplo interessante seria justamente desligar a internet, as configurações do retry estão no env

uma breve descrição das variaveis de ambiente:

`APP_SLOW_MO`: tempo entre as ações do bot
`APP_NAVIGATION_TIMEOUT_MS`: tempo máximo que a navegação pode demorar
`APP_PORTAL_DISMISS_BUTTON`: query selector para localizar o botão para o modal do portal
`APP_PORTAL_TOTAL_RECOLHER_TEXT`: o texto que utilizo para localizar os débitos no portal
`APP_PORTAL_FILTRO_DEBITOS_LABEL`: label para localizar o filtro de débitos (selecionamos a opção TODOS)
`APP_PORTAL_FILTRO_OPCAO_TEXT`: opção para seleção de débitos
`APP_PORTAL_FILTRO_ESPERA_MS`: delay para selecionar a opção TODOS
`APP_PORTAL_RESULT_TIMEOUT_MS`: tempo de espera para fazer a pesquisa
`APP_RETRY_MAX_ATTEMPTS`: maxímo de tentativas antes de retornar o erro
`APP_RETRY_WAIT_SECONDS`: tempo entre as tentativas
`APP_DB_RETRY_MAX_ATTEMPTS`: tentativas de se conectar com o banco de dados
`APP_DB_RETRY_WAIT_SECONDS`: tempo de espera entre as tentativas