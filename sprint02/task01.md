# Task 01 — Migrações PostgreSQL puro e conexão Supabase

## 1. Retirada do TimescaleDB

PostgreSQL puro é o único destino suportado, com Supabase conectado e provisionado.
O script de ativação do TimescaleDB foi removido, assim como a criação de
hypertables e as consultas aos catálogos da extensão. Código e documentação
foram alinhados à decisão, sem adicionar uma extensão substituta.

## 2. Identidade das leituras

Chaves adotadas no schema e nos repositories:

- Sensores: `(sensor_id, firebase_id)`.
- Boias: `(buoy_id, firebase_id)`.

Premissa: o ID não é reutilizado para outra leitura no equipamento.
`ON CONFLICT DO NOTHING` mantém a primeira versão recebida, mesmo se o horário
ou payload mudar. Leituras distintas no mesmo horário e IDs iguais em
equipamentos diferentes são preservados.

## 3. Schema e migrações PostgreSQL

- `000_initial_schema.sql`: base versionada de sensores, boias, checkpoints e
  índices, preservando tabelas existentes com `IF NOT EXISTS`.
- `001_etl_rejections.sql`: criação da tabela de rejeições em bancos existentes.
- `002_device_reading_identity.sql`: alteração das chaves das medições para
  equipamento/ID em tabelas comuns do schema `public`.
- `003_private_access.sql`: roles restritas e transferência das quatro tabelas para
  `etl_private`, preservando dados, chaves e índices.
- `004_measurement_timestamptz.sql`: conversão dos instantes das medições com a zona
  de origem explícita e reaplicação sem novo deslocamento.
- `app/sql/schema.sql`: entrada `psql` que inclui 000 → 001 → 002 → 003 → 004, sem duplicar DDL.
  A mesma sequência atende bancos novos e existentes; aplicação manual documentada,
  sem histórico automático de versões.

A migração 002 é transacional, não apaga linhas e aborta diante de duplicidades
na nova chave ou tabelas com particionamento/herança. A transferência de estruturas
da extensão antiga para tabelas comuns é uma operação separada.

Para bancos existentes, aplicar as migrações em ordem com
`psql -v ON_ERROR_STOP=1` antes de executar o worker atualizado.
`IF NOT EXISTS` não altera estruturas existentes; a migração 002 ajusta as chaves.
O arquivo de entrada usa `\ir` e exige `psql`; no SQL Editor, executar as migrações
individualmente em ordem. Após a 003, a entrada detecta o schema privado e reaplica
apenas 003/004, sem recriar objetos públicos. Não executar manualmente 000/001/002
depois da transferência. Não há registro automático de versões.

## 4. Instantes e índices

**Origem confirmada pelo responsável:** `America/Sao_Paulo`, tanto nas leituras
novas quanto no histórico do Firebase. Parser de sensores/boias produz datas com
fuso; migração 004 converte o histórico para `TIMESTAMPTZ` usando a zona explícita,
independentemente da configuração da sessão.

Horário de verão histórico é respeitado, sem offset fixo. Instantes ambíguos ou
inexistentes são rejeitados pelo parser e bloqueiam a migração para revisão manual.
`TIMESTAMPTZ` preserva o instante; o fuso de exibição é definido pelo cliente.
Migrações 000–004 aplicadas no Supabase; a 004 também está aplicada no PostgreSQL local.

Índices por equipamento/tempo foram preservados. Nenhum índice foi removido
sem medição.

## 5. Configuração da conexão por ambiente

`DatabaseConnection` usa os parâmetros validados de `Config`, com modelo sem
segredos em `.env.example`. Além de host/porta/banco/usuário/senha:

- `POSTGRES_SSLMODE`: padrão `disable` em loopback e `verify-full` em hosts remotos.
- `POSTGRES_SSLROOTCERT`: caminho opcional da CA, validado como arquivo legível.
- `POSTGRES_CONNECT_TIMEOUT`: segundos para conectar (padrão 10).
- `POSTGRES_STATEMENT_TIMEOUT_MS`: duração máxima de comando SQL (padrão 60000).
- `POSTGRES_LOCK_TIMEOUT_MS`: espera máxima por lock SQL (padrão 5000).
- `POSTGRES_SCHEMA`: padrão `etl_private`, validado como identificador simples.

Limites SQL aceitam `0` para desativação. Configurações inválidas são recusadas
antes de conectar, sem imprimir segredos. Supabase exige conexão direta ou pooler
session por causa da trava atual. Conexão real com Supabase por pooler session,
TLS 1.3 e `verify-full`, usando a CA do projeto.

O pooler sobrescreveu timeouts enviados nas opções de startup. A conexão agora
aplica `statement_timeout`, `lock_timeout` e `search_path` explicitamente na sessão,
sem deixar transação aberta. Os valores efetivos de 60000/5000 ms foram confirmados.
Falha na inicialização fecha a conexão, sem reutilizar uma sessão incompleta.

## 6. Permissões e privacidade

Migração 003 cria `etl_writer` e `ai_reader` como grupos sem login, senha ou
associação automática a usuários. Dono/migrações permanece separado do runtime.

- ETL: SELECT/INSERT em sensores e boias; SELECT/INSERT/UPDATE em checkpoints e
  rejeições. Sem DELETE, TRUNCATE ou alteração da estrutura.
- IA: somente SELECT em sensores e boias, sem acesso ao estado interno do ETL.
- `PUBLIC` e roles de Data API existentes têm acesso às quatro tabelas/schema revogado.

Decisão: schema privado, fora da lista de schemas expostos da Data API; sem
políticas RLS nesta etapa. Um futuro acesso via API exige revisão de grants/RLS.
Nenhuma IA ou credencial de IA foi criada. Logins e senhas devem ser provisionados
separadamente conforme `app/sql/README.md`; novas tabelas exigem grants explícitos.
Roles homônimas com atributos elevados, heranças ou propriedade de objetos
provocam erro para revisão manual, sem reaproveitar privilégios desconhecidos.

Migração 003 aplicada ao banco local. Login restrito `etl_runtime` associado
somente a `etl_writer`, com configuração privada em `.env.etl` (sem versionamento).
O `.env` administrativo foi preservado; o worker seleciona a credencial restrita
com `ETL_ENV_FILE=.env.etl`. Nenhum login de IA foi criado.
No Supabase, login `etl_runtime` provisionado com somente `etl_writer`; conexão
no pooler usa `etl_runtime.<project-ref>`. Configuração administrativa em
`.env.supabase` e restrita em `.env.supabase.etl`, ambas privadas e fora do Git.
Permissões de API revogadas, nenhuma credencial de IA criada. Não houve carga
permanente do histórico: as tabelas permanecem prontas para a primeira ingestão.
