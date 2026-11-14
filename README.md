<div align="center">

# 🌱 MoRHInGA | ETL Worker Python

**Pipeline de ingestão e persistência de dados ambientais de sensores e boias IoT**

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Firebase](https://img.shields.io/badge/Firebase-Realtime%20Database-FFCA28?logo=firebase&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-Time--series-1A63A4)

Projeto integrante do ecossistema de monitoramento ambiental **MoRHInGA**, desenvolvido no contexto do **GPADS**.

</div>

---

## 📌 Visão geral

O **MoRHInGA ETL Worker** é um serviço em Python responsável por transferir e estruturar medições ambientais armazenadas no **Firebase Realtime Database** para um banco **PostgreSQL com extensão TimescaleDB**.

Dispositivos de campo, como estações de sensores e boias, produzem leituras com nomes de campos e formatos de data próprios. O worker consulta essas leituras, normaliza seus campos, converte datas e valores quando necessário e persiste os registros em tabelas preparadas para consultas históricas.

**ETL** significa **Extract, Transform, Load** (*Extrair, Transformar e Carregar*):

1. **Extract:** consulta os nós `sensores` e `boias` no Firebase Realtime Database.
2. **Transform:** converte os registros em objetos de domínio `Sensor` e `Buoy`, padronizando campos e timestamps.
3. **Load:** insere os dados em `sensor_data` e `buoy_data`, evitando duplicações por chave primária.

O projeto atua como uma **camada de ingestão de dados**. Ele não é, por si só, uma interface web ou uma API HTTP.

O [diagnóstico técnico](docs/diagnostico.md) registra análises anteriores do projeto; algumas descrições antecedem a implementação incremental. Para configurar o ambiente, use o exemplo de variáveis neste README, sem valores reais.

O [plano de preparação para produção](docs/preparacao-producao.md) documenta os ajustes pendentes, critérios de validação e a arquitetura de deploy proposta. A hospedagem ainda não está implantada por este repositório.

## 🏗️ Arquitetura e fluxo

```mermaid
flowchart TD
    A[Estações e boias IoT] --> B[Firebase Realtime Database]
    B --> C[FirebaseClient]
    C --> D[ETLWorker]
    D --> E[Normalização dos sensores]
    D --> F[Normalização das boias]
    E --> G[SensorRepository]
    F --> H[BuoyRepository]
    G --> I[(PostgreSQL + TimescaleDB)]
    H --> I
    D --> J[Logs e contadores por ciclo]
```

### Funcionamento de um ciclo

Ao executar `python -m app.main`, o serviço:

1. Inicializa o logger e lê a configuração do arquivo `.env`.
2. Cria um `ETLWorker` com clientes e repositórios de persistência.
3. Lista os equipamentos de `/sensores` com uma consulta rasa.
4. Para cada equipamento, consulta `etl_checkpoint` e busca as chaves posteriores à última processada no nó `dados`. A consulta usa `start_at`, inclusivo, e descarta a leitura de fronteira.
5. Normaliza as leituras e grava os objetos em lote, em páginas SQL de 500 registros e uma transação por chamada. Após o commit dos dados, grava o checkpoint em outra transação.
6. Repete o processamento para `/boias`.
7. Registra as estatísticas do ciclo no terminal.
8. Aguarda o intervalo configurado e inicia uma nova consulta.

**Importante:** a implementação principal utiliza *polling* (consultas periódicas), com espera padrão de **60 segundos após o término de cada ciclo**; não é uma agenda fixa a cada minuto. Sem checkpoint, a primeira consulta pode carregar todo o histórico de um equipamento. O arquivo `app/firebase/readers/listener.py` contém uma classe preparatória, mas o listener em tempo real **ainda não está implementado**.

Falhas de normalização são registradas sem impedir as demais leituras, mas o checkpoint pode avançar além do registro inválido, que não será relido automaticamente. Uma falha na gravação do lote provoca rollback e impede o avanço daquele checkpoint. Exceções mais amplas durante um ciclo são registradas em `main.py`, que tenta executar o ciclo seguinte após o intervalo.

## 🧰 Tecnologias

| Tecnologia | Utilização |
| --- | --- |
| Python | Implementação do worker e regras de transformação |
| Firebase Admin SDK | Autenticação e leitura do Firebase Realtime Database |
| PostgreSQL | Persistência relacional das medições |
| TimescaleDB | Extensão de séries temporais e hypertables |
| psycopg2 | Conexão e transações SQL |
| python-dotenv | Carregamento das variáveis de ambiente |
| colorlog | Logs coloridos no terminal |
| unittest | Testes automatizados e de integração |

As versões exatas das dependências estão fixadas em [`requirements.txt`](requirements.txt).

## 📁 Estrutura do projeto

```text
etl_worker_python/
├── app/
│   ├── config/
│   │   └── config.py                  # Variáveis de ambiente
│   ├── database/
│   │   ├── connection.py              # Conexão e transações PostgreSQL
│   │   ├── sensor_repository.py       # Implementação alternativa/legada
│   │   └── buoy_repository.py         # Implementação alternativa/legada
│   ├── firebase/
│   │   ├── client.py                  # Firebase Admin e referências RTDB
│   │   ├── paths.py                   # Caminhos dos nós no Firebase
│   │   └── readers/
│   │       └── listener.py            # Listener ainda não implementado
│   ├── models/
│   │   ├── sensor.py                  # Modelo Sensor
│   │   └── buoy.py                    # Modelo Buoy
│   ├── repository/
│   │   ├── base.py                    # Inserção em lote e transações
│   │   ├── checkpoint_repository.py   # Progresso por origem e equipamento
│   │   ├── sensor_repository.py       # INSERT de sensores (fluxo principal)
│   │   └── buoy_repository.py         # INSERT de boias (fluxo principal)
│   ├── sql/
│   │   ├── init_timescale.sql         # Ativação da extensão TimescaleDB
│   │   └── schema.sql                 # Tabelas, hypertables, índices e checkpoint
│   ├── transformer/
│   │   ├── mapper.py                  # Mapeamento de nomes dos campos
│   │   ├── normalize.py               # Normalização das leituras
│   │   └── timestamp.py               # Conversão de data e hora
│   ├── utils/
│   │   └── logger.py                  # Configuração de logs
│   ├── worker/
│   │   └── etl_worker.py              # Orquestração da ingestão
│   └── main.py                        # Entrada e loop contínuo
├── docs/                               # Análises e preparação para produção
├── tests/                              # Testes unitários, integração e legado
├── .gitignore
├── README.md
└── requirements.txt
```

> Os repositórios em `app/repository/` são os utilizados em `ETLWorker`. Há também classes em `app/database/`; não presuma que essas implementações sejam intercambiáveis sem revisão.

## 🗃️ Estrutura dos dados no Firebase

O worker espera registros agrupados por equipamento, no formato geral:

```text
sensores/
  EST001/
    dados/
      <firebase_id>/
        hora: "2026-11-03 14:25:00"
        temperatura: 28.5
        umidade: 71
        ...

boias/
  BOIA001/
    dados/
      <firebase_id>/
        hora: "2026-11-03 14:25:00"
        ph: "7.2"
        ...
```

Esses valores são **exemplos ilustrativos**, não dados reais do sistema. Os nomes `EST001` e `BOIA001` representam os identificadores dos equipamentos; `<firebase_id>` representa a chave individual de uma leitura.

### Mapeamento de campos

| Origem: sensores | Destino |
| --- | --- |
| `ar`, `chuva`, `gas` | `ar`, `chuva`, `gas` |
| `luz`, `pressao`, `rpm` | `luz`, `pressao`, `rpm` |
| `temperatura`, `umidade`, `vento`, `volt` | `temperatura`, `umidade`, `vento`, `volt` |
| `hora` | `timestamp` |

| Origem: boias | Destino |
| --- | --- |
| `adc` | `adc` |
| `ph` | `ph` |
| `sensor_uv_v` | `sensor_uv_v` |
| `tensao_v` | `tensao_v` |
| `turbidez_v` | `turbidez_v` |
| `hora` | `timestamp` |

Os mapeamentos são definidos em `app/transformer/mapper.py`. Sensores e boias usam `hora` no formato `AAAA-MM-DD HH:MM:SS`. O formato antigo com campos em maiúsculas e `Data` separada não é aceito pelo mapper atual. Metadados como `endereco_ip` e `identificador` não são persistidos.

Em sensores e boias, valores numéricos ausentes ou vazios são convertidos para `None`; números e textos numéricos são convertidos para `float`. Booleanos, NaN, infinito e tipos inválidos são rejeitados. Sensores também possuem checagens de sanidade para alguns campos. As datas são convertidas sem informação de fuso horário; essa política precisa ser definida antes da produção.

## 🐘 Persistência e prevenção de duplicatas

O SQL em `app/sql/schema.sql` cria:

- **`sensor_data`**: medições de estações/sensores, incluindo temperatura, umidade, chuva, vento e outras grandezas.
- **`buoy_data`**: medições de boias, incluindo pH, turbidez, tensão e outras grandezas.
- **`etl_checkpoint`**: última chave processada por `(source, device_id)`, com data de atualização.

As duas tabelas são convertidas em **hypertables** por `timestamp` e possuem índices para consultas por tempo e equipamento.

A chave primária é composta por `(firebase_id, timestamp)`. Nas inserções, o projeto usa:

```sql
ON CONFLICT (firebase_id, timestamp)
DO NOTHING
```

Com isso, o reprocessamento da mesma leitura não gera outra linha com a mesma chave. **Atenção:** esse comportamento também significa que uma leitura já inserida **não é atualizada** caso seu conteúdo mude no Firebase.

Se os dados forem commitados, mas a gravação do checkpoint falhar, o próximo ciclo poderá relê-los com segurança quanto a duplicatas. A estratégia incremental depende da ordenação das chaves: novas leituras inseridas com chave anterior ao checkpoint não são buscadas automaticamente. Checkpoints não substituem backup nem uma política de reconciliação.

## 🚀 Instalação e execução local

### 1. Pré-requisitos

- Python compatível com as dependências do projeto (recomenda-se começar com **Python 3.12**).
- Git.
- Banco PostgreSQL com a extensão TimescaleDB instalada e disponível.
- Projeto Firebase Realtime Database acessível.
- Uma **chave de conta de serviço** com as permissões adequadas, fornecida de forma segura pela equipe responsável.

> Não inclua o JSON de credenciais em commits, mensagens, prints ou arquivos públicos.

### 2. Clone o repositório

```bash
git clone https://github.com/GpadsTech/etl_worker_python.git
cd etl_worker_python
```

### 3. Crie e ative um ambiente virtual

**Windows — Git Bash:**

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate
```

**Windows — PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instale as dependências

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5. Configure as variáveis de ambiente

Crie um arquivo `.env` na raiz do projeto:

```dotenv
FIREBASE_DATABASE_URL=https://SEU-PROJETO-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS=app/firebase/credentials/firebase_key.json

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=moringa
POSTGRES_USER=postgres
POSTGRES_PASSWORD=SUA_SENHA_LOCAL

ETL_INTERVAL_SECONDS=60
```

| Variável | Descrição |
| --- | --- |
| `FIREBASE_DATABASE_URL` | URL do Realtime Database do projeto Firebase |
| `FIREBASE_CREDENTIALS` | Caminho do JSON da conta de serviço, absoluto ou relativo à raiz do projeto |
| `POSTGRES_HOST` | Host do servidor PostgreSQL |
| `POSTGRES_PORT` | Porta do PostgreSQL; padrão `5432` |
| `POSTGRES_DB` | Nome do banco de dados |
| `POSTGRES_USER` | Usuário de conexão |
| `POSTGRES_PASSWORD` | Senha de conexão |
| `ETL_INTERVAL_SECONDS` | Intervalo entre ciclos; padrão `60` segundos |

O caminho da credencial acima é **um exemplo local** compatível com a forma como `FirebaseClient` resolve o arquivo. Crie as pastas necessárias e coloque o JSON fora do versionamento. O `.gitignore` já possui regras para configurações privadas e diretórios de credenciais, incluindo:

```gitignore
.env
.venv/
__pycache__/
*.pyc
**/credentials/
```

> O `.gitignore` não remove arquivos já rastreados nem saneia o histórico. Confirme a procedência das credenciais e revogue/substitua qualquer chave que tenha sido exposta. Em produção, use um secret file externo à imagem e ao Git.

### 6. Inicialize o TimescaleDB

Depois de criar o banco PostgreSQL e disponibilizar a extensão TimescaleDB, execute os scripts SQL **nesta ordem**:

```bash
psql -h localhost -U postgres -d moringa -f app/sql/init_timescale.sql
psql -h localhost -U postgres -d moringa -f app/sql/schema.sql
```

Adapte host, usuário e nome do banco conforme seu `.env`. O comando `psql` requer o cliente PostgreSQL instalado e disponível no terminal. O usuário do banco precisa ter permissões para criar a extensão, tabelas e índices, ou essas etapas devem ser executadas por um administrador.

### 7. Execute o ETL

Na raiz do projeto, com o ambiente virtual ativo:

```bash
python -m app.main
```

O worker executa ciclos continuamente até ser interrompido. Para encerrar com segurança, pressione **Ctrl+C**. O fluxo principal fecha a conexão com o banco ao finalizar.

### 8. Verifique a ingestão

Os logs mostram, separadamente para sensores e boias:

- **Recebidos:** registros em formato de objeto posteriores ao checkpoint, antes da validação dos campos.
- **Inseridos:** novas linhas persistidas no banco.
- **Já existentes:** leituras ignoradas por conflito na chave primária.
- **Erros:** leituras com falha na normalização ou persistência.

Para conferir no PostgreSQL:

```sql
SELECT COUNT(*) FROM sensor_data;
SELECT COUNT(*) FROM buoy_data;

SELECT sensor_id, timestamp, temperatura, umidade
FROM sensor_data
ORDER BY timestamp DESC
LIMIT 10;

SELECT buoy_id, timestamp, ph, turbidez_v
FROM buoy_data
ORDER BY timestamp DESC
LIMIT 10;
```

## 🧪 Testes

O repositório separa testes unitários offline de testes de integração. O teste de bootstrap legado está fora da suíte ativa.

Para executar somente os testes offline:

```bash
python -m tests
# Alternativa com unittest:
python -m unittest discover -s tests/unit -t . -q
```

Para um teste específico:

```bash
python -m unittest tests.unit.test_etl_worker
```

As integrações são puladas por padrão e exigem autorização explícita:

```bash
RUN_INTEGRATION=1 python -m tests.runner integration
```

No PowerShell, defina `$env:RUN_INTEGRATION = "1"` antes do comando e remova a variável ao terminar. Use somente credenciais e banco de teste. Os testes ativos de escrita SQL usam tabelas temporárias por sessão; isso não valida hypertables ou índices TimescaleDB. Consulte [TESTING.md](docs/TESTING.md) para detalhes.

## 🔧 Diagnóstico de problemas

| Sintoma | Possível causa e verificação |
| --- | --- |
| `FileNotFoundError` para credenciais | Revise `FIREBASE_CREDENTIALS` e a existência do JSON local |
| Erro de autenticação Firebase | Verifique a validade da conta de serviço e suas permissões |
| Erro de conexão com PostgreSQL | Confirme host, porta, banco, usuário, senha e servidor ativo |
| `function create_hypertable does not exist` | Instale/ative a extensão TimescaleDB antes do `schema.sql` |
| Erro ao converter timestamps | Compare os formatos das datas do Firebase com `timestamp.py` |
| Erro de conversão numérica | Verifique strings e valores dos campos de boias/sensores |
| Zero registros recebidos | Pode não haver chaves posteriores ao checkpoint; confira também os nós `sensores/{id}/dados` e `boias/{id}/dados` |
| Zero registros novos, mas registros existentes | O mecanismo de idempotência pode estar ignorando leituras já salvas |
| Push bloqueado pelo GitHub | Remova segredos dos commits e revise o `.gitignore`; não contorne a proteção |

## ⚠️ Escopo atual e melhorias futuras

### Já implementado no fluxo principal

- Consultas periódicas incrementais ao Firebase Realtime Database.
- Processamento separado de sensores e boias.
- Normalização de campos e timestamps.
- Persistência em lote no PostgreSQL/TimescaleDB.
- Checkpoint no banco por origem e equipamento.
- Proteção contra duplicatas via `ON CONFLICT DO NOTHING`.
- Logs e contadores por ciclo.
- Tratamento de falhas por registro.

### Pontos que ainda exigem atenção

- **Listener em tempo real:** `listener.py` ainda não implementa a escuta efetiva.
- **Carga inicial e backlog:** a leitura Firebase ainda não é paginada; todo o resultado por equipamento pode ficar em memória.
- **Integridade:** faltam armazenamento de rejeições, reprocessamento e política para chaves atrasadas.
- **Concorrência:** falta trava para impedir sobreposição de workers, inclusive durante deploys.
- **Atualização de leituras:** o mecanismo de conflito não atualiza registros existentes.
- **Operação:** faltam tratamento explícito de SIGTERM, timeouts, recuperação robusta de conexão e alertas de ausência de sucesso.
- **Deploy e segurança:** containerização, CI, validação de TLS, gestão de segredos e restauração de backups precisam ser preparados e testados.

O [plano de preparação para produção](docs/preparacao-producao.md) detalha prioridades e critérios de aceite. A proposta inicial é um Render Background Worker com uma instância e banco externo compatível com TimescaleDB; não há implantação realizada nem capacidade aprovada. Listener em tempo real é uma evolução opcional, não um requisito para hospedar o polling atual.

## 🤝 Contribuição

Para contribuir, crie uma branch com uma alteração focada, execute os testes pertinentes e abra um Pull Request descrevendo o objetivo, o impacto e os procedimentos de validação. Nunca inclua credenciais, senhas, dumps privados ou dados sensíveis nos commits.

## 🔗 Repositório e contexto

- **Código-fonte:** [GpadsTech/etl_worker_python](https://github.com/GpadsTech/etl_worker_python)
- **Contexto:** pipeline de dados ambientais do projeto **MoRHInGA / GPADS**.

---

<div align="center">

**MoRHInGA • Ingestão de dados ambientais para análise histórica**

</div>
