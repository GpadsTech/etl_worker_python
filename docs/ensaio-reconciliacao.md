# Ensaio de reconciliação, backup e retorno

## Escopo e limites

Neste projeto, a origem é o **Firebase** e o destino é o **Supabase**.
Não há transferência obrigatória de um banco local antigo. O retorno é ensaiado
restaurando um backup de dados em PostgreSQL vazio, reaplicando o delta pela
origem preservada e trocando o destino do worker somente após conferência.

O ensaio usa dois recortes: primeiras **100 chaves por equipamento** e **todo o
snapshot capturado**. Isso não aprova uma migração futura de volume desconhecido.
Para corte operacional, a liderança deve liberar ambiente, volume e janela.
Não rodar o ensaio destrutivo em produção.

Ferramentas:

- `app.operations.reconcile`: compara Firebase e PostgreSQL sem alterá-los.
- `app.operations.backup`: `pg_dump` de **dados apenas**, com snapshot consistente,
  manifesto por tabela e SHA-256; restauração somente em host local vazio.
- `app.operations.rehearse`: cria cluster descartável, restaura o backup e ensaia
  carga, delta, replay, disputa de processos e retorno.

Requisitos: Linux com Docker, imagem `postgres:18.7`, dependências Python instaladas,
CA confiável do Supabase e login com SELECT nas quatro tabelas. O cliente
`pg_dump` deve suportar a versão do servidor; não reutilizar um cliente mais antigo.
As migrações versionadas preparam o schema; o dump não restaura DDL, extensões,
hypertables, roles ou ACLs.

## 1. Preparar a janela e pausar escritores

1. Identificar a origem, o destino, o perfil de conexão e todos os agendadores/
   processos que escrevem o mesmo fluxo.
2. Suspender o agendamento e encerrar os workers com fechamento da conexão.
   Não matar nem pausar os equipamentos de campo: eles continuam enviando ao Firebase.
3. Confirmar que não há ciclo em execução. As ferramentas adquirem a mesma trava
   de sessão do ETL; se estiver ocupada, a operação é recusada.
4. **A trava é por banco.** Ela não impede um worker no destino antigo e outro no
   novo. Manter somente um agendador/destino ativo durante o corte e o retorno.
5. Registrar instante UTC, versão do código, arquivo de ambiente escolhido
   (nunca a senha), volume e responsáveis pela janela.

As ferramentas pausam escritores cooperantes enquanto mantêm a trava; não
substituem a suspensão de agendadores nem bloqueiam gravações administrativas
que ignorem essa convenção.

## 2. Backup antes da mudança

Executar na raiz, escolhendo diretórios novos e privados:

```bash
ETL_ENV_FILE=.env.supabase.etl .venv/bin/python -m app.operations.backup backup \
  --directory sprint02/task02-artifacts/NOVA_EXECUCAO/backup-before
```

O backup contém as quatro tabelas `etl_private`: medições, checkpoints e rejeições.
`data.dump`, `manifest.json` e `toc.json` devem permanecer juntos. O dump usa um
snapshot exportado da mesma transação que calculou os hashes, sob trava do ETL.
Não passa senhas na linha de comando: o perfil libpq é temporário, privado e
removido depois do uso. Artefatos têm permissão `0600`; diretórios de dados, `0700`.
São dados reais, não devem ir ao Git ou a canais públicos. Para operação contínua,
definir também cópia durável protegida, retenção e responsabilidade de recuperação.

## 3. Conferir origem e destino

```bash
ETL_ENV_FILE=.env.supabase.etl .venv/bin/python -m app.operations.reconcile \
  --output sprint02/task02-artifacts/NOVA_EXECUCAO/before
```

Resultados:

- `firebase.json`: snapshot privado da origem, somente leituras.
- `postgres.json`: conteúdo privado das quatro tabelas.
- `small.json` e `full.json`: contagens por tabela/equipamento/dia, extremos UTC,
  nulos por campo, amostras e diferenças por chave/campo.
- `daily.csv`: comparação por dia em `America/Sao_Paulo`.

A origem é normalizada pelas mesmas regras do ETL. A comparação verifica **todas
as colunas** das medições, não só contagens ou amostras. Checkpoints devem
corresponder à maior chave de cada equipamento; rejeições pendentes precisam
ser explicadas. Erros de normalização não viram sucesso silencioso.

O Firebase não oferece aqui uma transação conjunta com PostgreSQL. Fazemos duas
capturas da origem e exigimos hashes iguais durante a comparação. Se mudar,
registrar o delta e repetir até obter um recorte estável; não declarar igualdade
global sobre capturas inconsistentes.

## 4. Ensaiar o retorno sem tocar no Supabase

```bash
ETL_ENV_FILE=.env.supabase.etl .venv/bin/python -m app.operations.rehearse run \
  --snapshot sprint02/task02-artifacts/NOVA_EXECUCAO/before/firebase.json \
  --source-backup sprint02/task02-artifacts/NOVA_EXECUCAO/backup-before \
  --output sprint02/task02-artifacts/NOVA_EXECUCAO/rehearsal
```

O comando cria e remove seu próprio cluster Docker. A restauração do backup real
é validada por contagens e hashes das quatro tabelas. Em seguida, para cada recorte:

1. Usa leituras reais do snapshot, reservando a última chave de cada equipamento.
2. Carrega o conjunto inicial com o worker real e salva backup de dados/estado.
3. Com uma sessão segurando a trava, comprova que **outro processo** não ingere.
4. Libera a trava e apresenta as chaves reservadas como delta controlado.
5. Encerra o processo e retoma outro: não devem surgir novas inserções.
6. Recua checkpoints para forçar replay: medições não devem duplicar.
7. Com o escritor anterior já encerrado, restaura o backup pré-delta em outro
   banco vazio e retoma a mesma origem; deve recuperar o delta e reconciliar.

O delta é **controlado usando registros do snapshot**, não novas leituras
produzidas pelos equipamentos. O Firebase não é alterado. O ensaio comprova
recuperação de dados e estado no recorte, não um failover real de infraestrutura.

## 5. Reconciliar o delta real e retomar

Antes de iniciar um destino novo, conferir o estado restaurado e os checkpoints.
Nunca restaurar checkpoint à frente das medições/rejeições correspondentes.

1. Manter o escritor anterior parado.
2. Selecionar somente o perfil do destino aprovado.
3. Executar um ciclo controlado do worker ou iniciar o processo monitorado.
4. Repetir a comparação, registrando também o delta desde a captura anterior:

```bash
ETL_ENV_FILE=.env.supabase.etl .venv/bin/python -m app.operations.reconcile \
  --previous sprint02/task02-artifacts/NOVA_EXECUCAO/before/firebase.json \
  --output sprint02/task02-artifacts/NOVA_EXECUCAO/after
```

`delta.json` distingue chaves adicionadas, removidas, alteradas e chegadas com
chave anterior ao checkpoint. Leituras atrasadas não são capturadas automaticamente
pelo algoritmo incremental atual: bloquear o aceite e fazer backfill/reconciliação
explícita. Correções de leituras já persistidas também exigem decisão manual,
pois a política mantém a primeira versão.

Autorizar retomada normal somente com `passed=true`, origem estável, nenhuma
diferença inexplicada e somente um escritor configurado.

## 6. Retorno se houver falha

1. Suspender o novo escritor e o agendamento. Preservar os dados e evidências da falha.
2. Usar um ambiente de retorno **vazio**, com as mesmas migrações e acesso restrito.
3. Restaurar o backup pré-mudança, incluindo checkpoints e rejeições.
4. Conferir hashes antes de retomar. A ferramenta atual só aceita host loopback e
   destino vazio; não usar um túnel para contornar essa proteção:

```bash
ETL_ENV_FILE=ARQUIVO_PRIVADO_DO_RETORNO_LOCAL .venv/bin/python -m app.operations.backup restore \
  --directory sprint02/task02-artifacts/NOVA_EXECUCAO/backup-before --confirm-empty-local
```

5. Apontar **um único** worker para o retorno e reaplicar o delta a partir do Firebase.
6. Reconciliar novamente e somente então liberar o agendamento.

Não apagar ou sobrescrever o Supabase para simular retorno. Restauração remota
operacional requer procedimento específico aprovado; o comando acima a recusa.
Se o Firebase tiver removido dados pós-backup, a recuperação pelo replay não é
garantida: interromper a mudança e preservar/exportar o delta antes de prosseguir.

## Critério de conclusão

Guardar no relatório local: escopo, janela de captura, arquivos/hash do backup,
contagens e diferenças, delta real versus controlado, resultado de restauração/
retomada e limitações. Um ensaio só vale para o snapshot e volume registrados.
Os relatórios e dumps em `sprint02/` são locais e ficam fora dos commits.
