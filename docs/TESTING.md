# Testes

Executar os comandos na raiz do repositório, com as dependências instaladas no
ambiente virtual. A contagem atual é informada pelo runner; não usar números de
execuções antigas como critério de aprovação.

## Testes offline

Não consultam Firebase ou PostgreSQL e são a suíte padrão para desenvolvimento/CI:

```bash
.venv/bin/python -m tests
.venv/bin/python -m tests.runner tests.unit.test_timestamp
.venv/bin/python -m tests.runner tests.unit.test_reconciliation
.venv/bin/python -m unittest discover -s tests/unit -q
```

## Integração autorizada

Requer credenciais válidas e `RUN_INTEGRATION=1`. O arquivo escolhido por
`ETL_ENV_FILE` é privado; variáveis já exportadas prevalecem sobre seu conteúdo.

```bash
# PostgreSQL local, com login restrito:
ETL_ENV_FILE=.env.etl RUN_INTEGRATION=1 .venv/bin/python -m tests.runner integration

# Supabase, com login restrito:
ETL_ENV_FILE=.env.supabase.etl RUN_INTEGRATION=1 .venv/bin/python -m tests.runner integration

# Apenas um módulo:
ETL_ENV_FILE=.env.etl RUN_INTEGRATION=1 .venv/bin/python -m tests.runner tests.integration.test_timestamp_migration
```

No PowerShell, definir `$env:ETL_ENV_FILE` e `$env:RUN_INTEGRATION` antes do comando
Python e remover essas variáveis ao terminar.

### Isolamento e limites

- O Firebase é consultado somente para leitura. Os testes descobrem equipamentos
  dinamicamente; não dependem de IDs fixos da origem.
- Testes comuns de escrita usam tabelas temporárias por sessão, preservadas entre
  commits e removidas ao fechar a conexão, inclusive após falhas.
- A busca de tabelas temporárias exclui schemas permanentes; perda de sessão
  provoca erro em vez de reconectar sem o isolamento.
- Migrações de estrutura/instantes são exercitadas em tabelas temporárias;
  `test_migration_sequence` cobre a fase 000–002. Permissões reais têm suíte separada.
- Testes da trava usam sessões distintas e chave isolada.
- Sem dados na origem, um teste pode ser pulado; falhas de acesso ou formato
  não devem ser interpretadas como sucesso.
- Verificar falhas, erros **e pulados** no resumo. Uma suíte inteira pulada não
  comprova integração.

Esses testes não carregam o histórico nas tabelas definitivas, nem comprovam
capacidade, desempenho de índices, backups ou implantação do worker.

O ensaio operacional de backup/restauração, delta e retorno é separado dessas
suítes: seguir o [procedimento de reconciliação](ensaio-reconciliacao.md).
Ele gera evidências privadas e usa um cluster descartável para restauração.

## Permissões: somente cluster descartável

`tests.integration.test_private_access` cria roles e tabelas permanentes e faz
operações negativas de acesso. **Nunca executar no Supabase nem no banco local
habitual.** Usar cluster dedicado vazio, com credencial administrativa.

Além de configurar `POSTGRES_*` para esse destino, autorizar explicitamente:

```bash
RUN_INTEGRATION=1 RUN_PERMISSION_INTEGRATION=1 PERMISSION_TEST_DATABASE=permissions_test \
  .venv/bin/python -m tests.runner tests.integration.test_private_access
```

`PERMISSION_TEST_DATABASE` deve corresponder ao `POSTGRES_DB` configurado.
As variáveis de autorização não selecionam o destino: conferir também host,
porta e banco antes de executar. Sem a autorização extra, essa suíte é pulada.

Detalhes de roles e migrações: [guia SQL](../app/sql/README.md).

## Legado

`tests/legacy/test_bootstrap.py` está fora da suíte ativa. O bootstrap legado
não é necessário para a primeira carga: o worker atual lê o histórico quando
não há checkpoint.
