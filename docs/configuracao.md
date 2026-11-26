# Uma configuração para a aplicação

O arquivo **`.env` na raiz do projeto** contém tudo que a coleta precisa:
acesso ao Firebase, acesso restrito ao Supabase e os limites de execução.
O modelo da coleta padrão é [`.env.example`](../.env.example).
Os acessos opcionais de manutenção e teste têm modelos próprios, listados abaixo.

```bash
python -m app.main
```

Não é necessário escolher `.env.etl` ou `.env.supabase.etl`. Esses perfis antigos
foram consolidados. **Não coloque a senha de administrador no `.env` da coleta.**

## O que preencher

| Grupo | Variáveis |
| --- | --- |
| Firebase | `FIREBASE_DATABASE_URL`, `FIREBASE_CREDENTIALS` |
| Banco | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SCHEMA` |
| Segurança da conexão | `POSTGRES_SSLMODE`, `POSTGRES_SSLROOTCERT` |
| Limites do banco | `POSTGRES_CONNECT_TIMEOUT`, `POSTGRES_STATEMENT_TIMEOUT_MS`, `POSTGRES_LOCK_TIMEOUT_MS` |
| Coleta | `ETL_INTERVAL_SECONDS`, `ETL_PAGE_SIZE`, `ETL_LOOKBACK_RECORDS` |

O modelo contém as 16 opções da aplicação de forma explícita. O código continua tendo padrões
para opções como tamanho de grupo e intervalo. Credenciais reais precisam ser
preenchidas, nunca copiadas para o Git ou para mensagens públicas.

No Supabase, usar o usuário restrito `etl_runtime.<project-ref>`, conexão direta
ou pooler de sessão, `verify-full` e o certificado confiável do projeto.
O JSON do Firebase e o certificado são arquivos separados, não arquivos `.env`;
os caminhos no `.env` precisam apontar para arquivos existentes.

## Como a configuração é carregada

`app/config/config.py` carrega o `.env` da raiz do repositório, independentemente
da pasta de onde foi iniciado. Os comandos de coleta, reprocessamento,
conferência e backup usam esse mesmo carregamento; não escolhem perfis próprios.

Variáveis já definidas no processo têm prioridade sobre o arquivo. Isso permite
injetar segredos na hospedagem sem criar um `.env` dentro da imagem.
Se não existir `.env`, esse modo de configuração por variáveis continua disponível.

## Administração e testes: exceção explícita

Migrações, correções aceitas e backup da auditoria exigem poderes que a coleta
não deve ter. Esses acessos ficam em `config-private/`, dentro do projeto, mas
**fora do Git** e com acesso restrito. Não são carregados automaticamente:

```text
.env                              # Coleta no Supabase
.env.example                      # Modelo sem credenciais reais
config-private/
  supabase-admin.env              # Administração do Supabase
  local-admin.env                 # Administração local
  local-etl.env                   # Coleta local
```

Nunca publicar, anexar ou incluir os arquivos reais de `config-private/` em
imagens de distribuição. Apenas os três modelos sem segredos podem entrar no Git:

| Modelo | Arquivo real |
| --- | --- |
| [`supabase-admin.env.example`](../config-private/supabase-admin.env.example) | `config-private/supabase-admin.env` |
| [`local-admin.env.example`](../config-private/local-admin.env.example) | `config-private/local-admin.env` |
| [`local-etl.env.example`](../config-private/local-etl.env.example) | `config-private/local-etl.env` |

Copiar o modelo somente se o arquivo real ainda não existir, preencher os valores
e proteger o arquivo. Não sobrescrever configurações já preenchidas.
No Linux, a pasta usa permissão `0700`, e os arquivos, `0600`.

Para esses comandos, ainda existe `ETL_ENV_FILE`, **opcional**, informado no
processo. Exemplo selecionando o arquivo administrativo:

```bash
ETL_ENV_FILE=config-private/supabase-admin.env \
  python -m app.reprocess_history correct --help
```

O arquivo selecionado substitui o `.env` padrão; os dois não são combinados.
Variáveis já exportadas ainda têm prioridade: remover valores antigos de
`POSTGRES_*`, `FIREBASE_*`, `ETL_*` antes de selecionar outro destino.
Um arquivo indicado mas inexistente causa erro, sem tentar outro perfil.
Caminhos relativos de `ETL_ENV_FILE` são resolvidos a partir da raiz do projeto.

Não definir `ETL_ENV_FILE` dentro do próprio `.env`: a escolha ocorre antes de
ler o arquivo. Se o terminal ainda tiver uma seleção antiga, removê-la:

```bash
unset ETL_ENV_FILE
```

No PowerShell: `Remove-Item Env:ETL_ENV_FILE -ErrorAction SilentlyContinue`.

Nesta máquina, os três arquivos reais de `config-private/` foram recuperados dos
perfis originais. Uma cópia externa em `~/.config/etl_worker_python/profiles/`,
numa pasta datada, foi mantida como segurança. Em um clone novo, esses arquivos
privados não existem: preencher os modelos com as credenciais autorizadas.
O commit preserva o código e os modelos, **não as senhas**.

## Banco local opcional

O destino padrão atual é o Supabase. O Compose atende apenas ao banco local e
usa variáveis `LOCAL_POSTGRES_*` separadas. Isso evita usar a senha do Supabase
para inicializar um banco local.

Fornecer `LOCAL_POSTGRES_PASSWORD` por meio seguro no processo e então executar:

```bash
docker compose up -d --wait postgres
```

Os padrões locais são banco `moringa`, usuário administrativo `etl_local` e porta
`5433`. Os opcionais são `LOCAL_POSTGRES_DB`, `LOCAL_POSTGRES_USER` e
`LOCAL_POSTGRES_PORT`. Não colocar credenciais administrativas locais no `.env`
da coleta. Em volume existente, alterar essas variáveis não muda usuários/senhas
nem reconfigura o banco já criado.

Para testar contra o PostgreSQL local com o acesso restrito já configurado:

```bash
ETL_ENV_FILE=config-private/local-etl.env RUN_INTEGRATION=1 \
  python -m tests.runner integration
```

Não manter dois coletores ativos para o mesmo fluxo em destinos diferentes.
