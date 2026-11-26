# Migrações e acesso privado

Aplicar com o ETL parado, usando o dono das tabelas/schema com permissão
`CREATEROLE`. Essa credencial administrativa não deve ser usada pelo worker.

```bash
psql -h localhost -p 5433 -U USUARIO_MIGRACAO -d moringa -v ON_ERROR_STOP=1 -f app/sql/schema.sql
```

## Ordem e atualização

- 000: base de sensores, boias, checkpoints e índices.
- 001: rejeições.
- 002: identidade por equipamento/ID.
- 003: roles de acesso e transferência das quatro tabelas para `etl_private`.
- 004: instantes de sensores e boias em `TIMESTAMPTZ`.
- 005: auditoria administrativa de correções históricas (`etl_corrections`),
  sem ampliar permissões do ETL ou da IA.

Em banco que já recebeu 000/001/002, executar 003, 004 e 005. A transferência usa
`ALTER TABLE SET SCHEMA`, preservando linhas, chaves e índices, sem cópias em
`public`. Se houver tabelas homônimas nos dois schemas, a migração aborta sem
escolher ou apagar dados.

`schema.sql` requer **psql** e inclui as migrações sem duplicar DDL. Ao detectar
o schema privado já implantado, não reaplica a base pública: executa apenas 003/004/005,
que aceitam reaplicação. Isso não substitui um histórico de versões. Após 003,
não executar manualmente as migrações antigas 000/001/002: elas usam `public`.
No SQL Editor do Supabase, aplicar somente as migrações pendentes individualmente.
Se 004 já estiver aplicada, executar somente 005; a ingestão não depende da
auditoria, mas a aplicação de correções exige essa tabela.
Procedimento: [correção histórica](../../docs/firebase-incremental.md).

## Contrato temporal

O responsável confirmou `America/Sao_Paulo` para sensores, boias e todo o
histórico do Firebase. A 004 converte as colunas `timestamp` das duas tabelas com
`USING timestamp AT TIME ZONE 'America/Sao_Paulo'`. Preserva índices, chaves,
permissões e colunas já em `TIMESTAMPTZ`; não reaplica deslocamentos.

A conversão usa as regras IANA históricas, incluindo horário de verão, e não
depende do timezone da sessão. Horários ambíguos, inexistentes ou não finitos
abortam a migração inteira para revisão manual. O parser também rejeita gaps e
sobreposições; o ETL mantém esses registros na quarentena de rejeições.
O ambiente Python precisa da base IANA do sistema (ou pacote `tzdata`).

`TIMESTAMPTZ` guarda o instante, não o nome da zona de origem. O cliente pode
mostrar UTC ou outro fuso sem alterar o valor. Para hora local, consultar
`timestamp AT TIME ZONE 'America/Sao_Paulo'`.

## Perfis

| Role de grupo | Medições | Checkpoints e rejeições | Estrutura |
| --- | --- | --- | --- |
| `etl_writer` | SELECT, INSERT | SELECT, INSERT, UPDATE | Sem alteração |
| `ai_reader` | SELECT | Sem acesso | Sem alteração |
| Dono/migrações | Administração | Administração | Administração |

Os grupos são `NOLOGIN`, sem senha, sem privilégios administrativos e sem
associação automática a usuários. Não há DELETE/TRUNCATE para ETL ou IA.
A 003 aborta se encontrar roles homônimas com atributos elevados, herança
de outras roles ou propriedade de objetos; requer revisão manual, não reaproveita
permissões desconhecidas.
Novas tabelas precisam de grants explícitos: não há leitura automática da IA
nem escrita automática do ETL em futuras tabelas.

## Credencial do ETL

Provisionar separadamente com o administrador, fora de arquivos versionados:

```sql
CREATE ROLE etl_runtime LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS;
GRANT etl_writer TO etl_runtime;
```

Definir a senha por canal seguro; no **psql**, usar `\password etl_runtime`.
Configurar `POSTGRES_USER`/`POSTGRES_PASSWORD` com essa credencial e
`POSTGRES_SCHEMA=etl_private`. Não associar o worker a uma role proprietária,
administrativa ou à `ai_reader`.

Para manter o `.env` administrativo local separado, guardar a configuração do
worker em `.env.etl` (permissão `0600`, ignorado pelo Git) e executar
`ETL_ENV_FILE=.env.etl .venv/bin/python -m app.main`. Não trocar as credenciais
de inicialização do Docker pelas da role restrita. Variáveis exportadas pelo
processo prevalecem sobre o arquivo selecionado.

Não criar credencial da IA agora. Quando existir uma aplicação consumidora,
provisionar login dedicado e conceder apenas `ai_reader`, sem outras memberships.
No Supabase, usar host/porta/identificação de usuário próprios do endpoint escolhido;
validar o formato do login no painel, sem supor que o nome isolado basta no pooler.

No pooler compartilhado, o login provisionado usa `etl_runtime.<project-ref>`.
As configurações privadas do projeto ficam em `.env.supabase` (administração)
e `.env.supabase.etl` (worker). Para iniciar a ingestão:

```bash
ETL_ENV_FILE=.env.supabase.etl .venv/bin/python -m app.main
```

Usar `verify-full`, CA do projeto e porta de sessão. A conexão aplica schema e
timeouts explicitamente após abrir a sessão para evitar valores sobrescritos
pelo pooler. Nenhum desses arquivos privados deve ser versionado.

## Data API

**Não incluir `etl_private` nos schemas expostos da Data API do Supabase.**
O schema privado restringe acesso por ACL; não são criadas políticas RLS nem
views públicas. A migração revoga acesso de `PUBLIC` e, quando existentes, de
`anon`, `authenticated` e `service_role`, inclusive grants anteriores nas tabelas.
Isso não remove o acesso legítimo do dono/administradores.

Se futuramente for necessário expor dados, tratar como nova alteração de
segurança: definir views/tabelas autorizadas, grants e RLS antes de expor o schema.
Manter as credenciais de migração e do ETL fora do cliente e da aplicação da IA.

## Validação isolada de permissões

A suíte `tests.integration.test_private_access` cria objetos e roles reais:
usar **cluster descartável**, nunca o banco de desenvolvimento ou o Supabase.
Exige `RUN_INTEGRATION=1`, `RUN_PERMISSION_INTEGRATION=1` e
`PERMISSION_TEST_DATABASE` igual ao `POSTGRES_DB` do banco vazio autorizado.
Os demais testes de integração continuam usando tabelas temporárias.
