# Firebase incremental, atraso e correção histórica (T05)

## Contrato da origem

Cursor: **push ID Firebase de 20 caracteres**, por `(origem, equipamento)`.
O ID identifica a leitura; `hora` continua sendo o horário da medição em
`America/Sao_Paulo`, não um instante confiável de chegada. Leituras com horários
iguais e IDs diferentes são preservadas.

Inspeção somente leitura encontrou 9.293 IDs compatíveis e confirmou consultas
`order_by_key`, `start_at`, `end_at`, `limit_to_first` e `limit_to_last`.
A ordenação por chave tem índice nativo no RTDB: não requer `.indexOn` de `hora`.
Não alteramos regras nem consultamos/publicamos sua configuração privada.
As consultas foram verificadas com a conta de serviço; isso não prova permissões
de clientes web/mobile. Um produtor que mudar o formato precisa de nova avaliação;
chaves incompatíveis interrompem a página, sem avançar silenciosamente.

## Algoritmo

1. Adquire a mesma trava PostgreSQL de sessão usada pela ingestão/manutenção.
2. Lê o checkpoint do equipamento e a maior chave atual (horizonte do ciclo).
3. Se houver checkpoint, reconsulta até N chaves anteriores/incluindo a fronteira,
   também em páginas. Só normaliza IDs ainda ausentes das medições **e** rejeições,
   inclusive rejeições resolvidas: coleta normal não reabre nem corrige registros.
4. Percorre as chaves posteriores até o horizonte, em ordem crescente local.
5. Para cada página, confirma medições e rejeições antes de confirmar seu checkpoint.
   São commits separados, não uma transação única. Falha em qualquer persistência
   impede o checkpoint; falha no checkpoint impede a próxima página do equipamento.
6. No próximo ciclo, reler é seguro pela identidade `(equipamento, firebase_id)`.

Sem checkpoint, o histórico inteiro é percorrido **por páginas**, não baixado
inteiro. A descoberta do início da janela também usa páginas reversas limitadas,
sem baixar a janela inteira de uma vez. Consultas usam até `ETL_PAGE_SIZE + 1` entradas porque
`start_at` é inclusivo; a fronteira é excluída localmente. A exclusão dessa
fronteira na origem não faz saltar o item excedente. JSON fora de ordem é ordenado;
respostas repetidas/fora de faixa são recusadas, sem loop infinito.

## Configuração e limites

| Variável | Padrão | Valores |
| --- | --- | --- |
| `ETL_PAGE_SIZE` | 500 | 1–10.000 |
| `ETL_LOOKBACK_RECORDS` | 1.000 | 0–10.000; 0 desativa |

A janela é **quantidade de chaves existentes até o checkpoint**, não dias/horas;
inclui a própria fronteira quando ela ainda existe. Não é promessa de atraso
máximo temporal. Inserções novas com ID posterior entram normalmente mesmo com
`hora` antiga. Inserções com ID anterior só entram automaticamente se estiverem
na janela no momento da reconsulta.

O horizonte evita perseguir continuamente a cauda, mas **não é um snapshot
transacional do Firebase**. Uma leitura inserida atrás de uma página já lida
depende da janela futura ou do backfill. Registros excluídos da origem não são
apagados no PostgreSQL. Volume extremo ou atrasos arbitrários exigem ajustar a
janela e fazer reconciliação periódica, não apenas aumentar o tamanho da página.

As contagens do worker descrevem registros efetivamente enviados à classificação;
IDs conhecidos na reconsulta não contam como recebidos/ignorados.
Checkpoint não representa o horário da medição nem prova que nunca surgirá uma
leitura anterior a ele.

## Recuperação explícita

Parar o worker para uma manutenção previsível. Nunca editar o checkpoint para
forçar recuperação: os comandos abaixo não o movem e disputam a mesma trava.
Substituir os placeholders por push IDs reais, entre aspas.

### 1. Leitura antiga ausente do banco (backfill)

Com o login restrito do `.env` padrão:

```bash
python -m app.reprocess_history backfill \
  --source boias --device-id BOIA001 --start 'ID_INICIAL' --end 'ID_FINAL'
```

Intervalo inclusivo obrigatório e paginado. Só insere identidades desconhecidas;
erros de dados viram rejeições duráveis. Falha operacional interrompe com código
não zero; repetir o mesmo intervalo é seguro. Alterar o normalizador não atualiza
medições aceitas durante backfill.

### 2. Leitura já rejeitada

Usar `app.reprocess_rejections`, com filtros e `--refresh-from-firebase` se a
origem foi corrigida. Preserva o payload rejeitado e só resolve após persistência.
Não substitui medições aceitas.

### 3. Correção de medição já aceita

Ingestão normal e backfill mantêm a **primeira versão**. Para substituí-la:

1. Aplicar a migração `005_historical_corrections.sql` com o administrador.
2. Fazer backup administrativo incluindo a auditoria, revisar a mudança e motivo.
3. Executar prévia (padrão, sem `--apply`) com arquivo administrativo em
   **`config-private/`, fora do Git**, sem alterar o `.env` restrito da coleta:

```bash
ETL_ENV_FILE=config-private/supabase-admin.env python -m app.reprocess_history correct \
  --source boias --device-id BOIA001 --key 'ID_DA_LEITURA' \
  --reason 'Motivo aprovado da correção'
```

4. Revisar os valores na origem/banco e os hashes retornados. Aplicar:

```bash
ETL_ENV_FILE=config-private/supabase-admin.env python -m app.reprocess_history correct \
  --source boias --device-id BOIA001 --key 'ID_DA_LEITURA' \
  --reason 'Motivo aprovado da correção' --apply \
  --expected-hash 'BEFORE_SHA256_DA_PREVIA' \
  --expected-source-hash 'AFTER_SHA256_DA_PREVIA'
```

O comando relê e normaliza a origem, bloqueia a linha com `FOR UPDATE` e exige
os dois hashes: se o banco **ou a origem normalizada** mudou desde a prévia,
recusa. Não permite mudar equipamento/ID. Ausência ou payload inválido é erro,
não exclusão. Uma mudança apenas em campos descartados pelo normalizador não
altera o hash nem os valores persistidos.

UPDATE e auditoria com valores anterior/posterior, motivo, usuário SQL e instante
são confirmados na mesma transação. Falha na auditoria desfaz o UPDATE.
Repetir uma aplicação já feita com hash antigo é recusado; uma nova prévia sem
diferenças resulta em no-op. A role `etl_writer` continua sem UPDATE nas medições
e sem acesso a `etl_corrections`; a IA e roles da Data API também não recebem acesso.
Administradores ainda podem alterar a auditoria: não é armazenamento imutável
contra o próprio dono.

A auditoria fica em `etl_private`, fora da Data API. Backups administrativos
incluem essa quinta tabela quando instalada; backup com login restrito após 005
é recusado por falta de acesso, em vez de omitir auditoria. Manter artefatos
privados, acesso e retenção controlados. O manifesto informa as tabelas incluídas.

## Validação

`tests/unit/test_pagination.py`: limites, fronteira apagada, repetição, horizonte,
ordem e formato; `test_paginated_worker.py`: falhas e retomada em memória.
`tests/integration/test_pagination.py` repete os cenários com commits SQL reais
em tabelas TEMP; `test_historical_corrections.py` valida prévia, hashes e rollback.
Interrupções são injetadas/controladas; não equivalem a ensaio de queda de máquina
nem a capacidade de produção. A suíte de permissões exige cluster descartável.
