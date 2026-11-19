# Preparação do ETL Worker para produção

Data da análise: 14/11/2026.

Atualização de implementação: 16/11/2026.

Atualização do banco (18/11/2026): PostgreSQL puro no Supabase é o destino
escolhido. A extensão de séries temporais foi retirada do projeto.

**Estado: preparação em andamento, sem liberação para produção.** Há implementações locais nos itens 3.1 e 3.3, com testes offline; as validações de integração continuam pendentes. A plataforma, a região, o orçamento e a capacidade ainda dependem de validação da equipe. Não houve contratação, implantação ou acesso aos serviços reais nesta análise.

## 1. Base atual

O ponto de entrada `python -m app.main` executa continuamente o ETL e espera `ETL_INTERVAL_SECONDS` após cada ciclo (padrão: 60 segundos).

O fluxo ativo já possui:

- Leitura incremental por chave Firebase, origem e equipamento.
- Checkpoints persistidos em `etl_checkpoint`.
- Normalização de sensores e boias.
- Inserts em páginas SQL de 500 registros, com uma transação por chamada de `insert_many`.
- Idempotência por `(equipamento, firebase_id)` com `ON CONFLICT DO NOTHING`.
- Commit dos dados antes da gravação do checkpoint, em transações separadas.
- Rejeições duráveis em `etl_rejections`; dados inválidos não impedem o avanço após persistir os resultados.
- Isolamento de erros SQL de dados/integridade para preservar os registros válidos do lote.
- Reprocessamento opcional, fora do fluxo normal de extração/classificação.
- Trava de sessão PostgreSQL compartilhada entre ingestão e reprocessamento.
- Logs e contadores por ciclo.

Não há API HTTP no fluxo principal nem necessidade de disco local persistente para guardar o progresso. A credencial Firebase é um arquivo de configuração, não o estado da ingestão.

Os testes offline cobrem rejeições, replay, avanço de checkpoint, aquisição/liberação da trava e proibição de reconexão durante uma operação protegida. Bootstrap e migrações foram testados em PostgreSQL 16 descartável; carga, rede, TLS e integração com Supabase continuam pendentes. Testes com tabelas temporárias não comprovam desempenho dos índices. Executar `python -m tests` para a contagem atual.

## 2. Arquitetura de deploy proposta

```text
GitHub → CI (testes/build) → Imagem Docker
                                 ↓
                           CD (migrações)
                                 ↓
                           Render Cron diário
                             ├── HTTPS → Firebase RTDB
                              ├── TLS → PostgreSQL do Supabase
                             └── Logs, métricas e alertas
```

Configuração inicial proposta:

| Item | Proposta |
| --- | --- |
| Processo | Render Cron diário, sem servidor HTTP |
| Comando previsto | `python -u -m app.run_once` — módulo ainda a implementar |
| Agenda proposta | `0 3 * * *` — diariamente às 03:00 UTC, a confirmar |
| Compute candidato | `0.5c-512mb`: 0,5 CPU / 512 MB RAM |
| Concorrência | Uma execução do job, com trava no banco contra outros processos |
| Disco persistente | Indisponível no cron; estado deve permanecer no banco |
| Segredos | Variáveis do provedor e JSON Firebase em secret file |
| Banco | PostgreSQL do Supabase, externo ao worker, com backups a configurar |
| Região | Escolher considerando banco, Firebase, latência e residência dos dados |
| Monitoramento | Sucesso da ingestão, não apenas existência do processo |

A decisão foi atualizada para Render Cron diário, com estimativa de 1–2 horas ativas por dia, conforme a [ADR de hospedagem](adr-hospedagem.md). A medição local de 9.293 leituras atingiu aproximadamente 70 MiB de RSS em simulação sem inserts; o plano de 512 MB é candidato a homologação, não capacidade aprovada. O destino é PostgreSQL puro no Supabase; conexão segura e permissões ainda precisam de validação. Somente se Render não for viável, considerar a mesma imagem de execução única em VM Linux com systemd timer.

Não são necessários Kubernetes, Redis, Celery ou Airflow para executar o fluxo atual.

### Escolha do banco

Usar PostgreSQL puro do Supabase, sem extensão adicional. `app/sql/schema.sql`
cria tabelas comuns e índices por equipamento/tempo no schema privado `etl_private`.
As roles de grupo `etl_writer` e `ai_reader` não possuem login; credenciais
dedicadas devem ser provisionadas separadamente. Não expor o schema na Data API.
Ver [permissões](../app/sql/README.md). O script de ativação da
extensão antiga foi removido; não existe mais dependência de catálogos dela.

Para bancos existentes, aplicar as migrações versionadas antes de atualizar o
worker. A 002 exige tabelas comuns, sem particionamento/herança, e bloqueia
duplicidades sem removê-las. Transferência de estruturas antigas não é automática.
Validar endpoint, TLS, permissões e modo session do pooler no Supabase.

### Execução agendada

`ETLWorker.run_once()` existe como método, mas não há um comando dedicado de execução única com fechamento garantido e código de saída operacional. **Não agendar `app.main` como cron**, pois ele não termina.

A operação aceita atualização diária. Implementar essa entrada com a trava existente, encerramento garantido e resultado que distinga rejeição persistida de falha operacional. As 1–2 horas estimadas não são espera programada: encerrar ao terminar os pendentes.

## 3. Ajustes obrigatórios antes da liberação

Os itens abaixo exigem implementação ou comprovação. Os avanços locais são indicados em cada seção e não substituem a validação em homologação. Responsabilidades são sugeridas; a equipe precisa atribuir responsáveis nominais.

### 3.1. Preservar e reprocessar registros rejeitados

**Prioridade: bloqueador de integridade. Responsável sugerido: desenvolvimento.**

**Situação atual:** implementado localmente. `etl_rejections` preserva origem, equipamento, chave Firebase, payload, motivo, tentativas e datas. O worker processa os demais registros e avança o checkpoint após salvar válidos e rejeitados, inclusive quando todos forem inválidos. A existência de rejeições não exige intervenção manual nem bloqueia ciclos futuros. Erros SQL de dados/integridade são isolados por registro após rollback do lote. Falhas operacionais que impeçam persistência mantêm o checkpoint anterior.

O comando de reprocessamento é opcional para manutenção; não pressupõe alterações manuais no Firebase nem integra o fluxo normal. Existe migração aditiva para bancos existentes em `app/sql/migrations/001_etl_rejections.sql`.

Pendências:

- Validar migração, inserts e replay contra PostgreSQL em homologação.
- Definir acesso restrito, retenção e sanitização dos payloads e mensagens no ambiente operacional.

**Critério de aceite:** leitura inválida fica recuperável após o avanço do checkpoint; falha ao salvar a rejeição não causa descarte silencioso; correção e reprocessamento são testados.

### 3.2. Validar ordenação, atrasos e reconciliação

**Prioridade: bloqueador de integridade. Responsáveis sugeridos: desenvolvimento e firmware.**

A consulta usa `order_by_key()` e `start_at()`, e o worker compara as chaves com operadores de string. A estratégia pressupõe que leituras novas tenham chaves posteriores ao checkpoint e que essa comparação corresponda à ordenação utilizada na origem.

Ajustes:

- Documentar como todos os dispositivos geram as chaves, inclusive offline.
- Testar ordenação com os formatos reais; não presumir que chaves arbitrárias ou numéricas tenham o mesmo comportamento de push IDs.
- Definir tratamento de leituras inseridas tardiamente com chave anterior ao checkpoint.
- Implementar estratégia de reconciliação/backfill, por janela ou varredura controlada, conforme o contrato da origem.
- Manter explícita a política append-only: correções de leituras existentes não são atualizadas pelo insert atual.

**Critério de aceite:** testes cobrem fronteira inclusiva, inserção atrasada, backfill, replay e política de correção; a equipe aprova as garantias e limitações.

### 3.3. Impedir workers concorrentes

**Prioridade: bloqueador operacional. Responsável sugerido: desenvolvimento.**

**Situação atual:** implementado localmente em `app/database/connection.py`. O checkpoint sozinho não fornece exclusão mútua; agora `pg_try_advisory_lock` com chave bigint fixa protege o ciclo completo, as chamadas públicas por origem e o reprocessamento. Todos os repositórios continuam na mesma sessão da trava.

Comportamento:

- Uma aquisição por operação externa, sem empilhar locks nas chamadas aninhadas.
- Se estiver ocupada, o loop pula o ciclo e aguarda; o reprocessamento termina com código `1`, sem consultar o Firebase.
- A trava sobrevive aos commits/rollbacks dos repositórios e é liberada na saída, inclusive em exceções.
- Perda ou substituição da conexão impede continuar/reconectar dentro da operação. Uma nova operação exige nova aquisição.
- Falha ao liberar a trava fecha a sessão original; o PostgreSQL libera a trava ao encerrar a sessão.
- Exige conexão direta ou pooler em modo **session**; modo transaction é incompatível.

Validação disponível:

- `tests/unit/test_worker_lock.py`: aquisição, contenção, aninhamento, limpeza, perda/substituição da sessão e proteção das entradas públicas.
- Testes do worker verificam interrupção imediata ao perder a trava, sem categorizar essa falha como leitura inválida.
- `tests/integration/test_worker_lock.py`: testes opt-in com duas sessões PostgreSQL, chave aleatória isolada e tabelas temporárias; ainda não executados contra serviço real.

Pendências:

- Executar os testes reais e ensaiar dois processos, encerramento abrupto e reconexão em homologação.
- Confirmar o modo de conexão/pooler e disponibilidade das funções PostgreSQL no provedor.
- Na primeira implantação, parar versões antigas sem trava: elas não participam da exclusão mútua.

**Critério de aceite:** ao iniciar dois processos, apenas um executa o trabalho protegido; término abrupto libera a trava; recuperação de conexão exige nova aquisição.

### 3.4. TLS, timeouts e recuperação de conexões

**Prioridade: bloqueador de segurança e disponibilidade. Responsáveis sugeridos: desenvolvimento e infraestrutura/DBA.**

`app/database/connection.py` configura TLS, CA e timeouts de conexão/SQL por
variáveis de ambiente; ver `.env.example` e README. Hosts remotos usam
`verify-full` por padrão; loopback usa `disable` se o modo não for informado.
A validação real de certificado/hostname no Supabase continua pendente.
A repetição do ciclo com espera fixa não equivale a uma política robusta de recuperação.

Ajustes:

- Validar TLS PostgreSQL com `sslmode=verify-full`, CA confiável e hostname correto no Supabase.
- Validar os timeouts PostgreSQL configurados e implementar limites de espera de rede Firebase.
- Descartar sessões inutilizáveis, tratar rollback que falha e reconectar com segurança.
- Aplicar tentativas limitadas com espera progressiva e jitter para falhas transitórias.
- Diferenciar erro transitório de credencial inválida, configuração incorreta e registro inválido.
- Validar configuração na inicialização, incluindo intervalo positivo, sem imprimir segredos.

**Critério de aceite:** conexão sem TLS válido é recusada; indisponibilidade temporária não prende o processo indefinidamente; o worker volta a ingerir sem duplicação e respeitando a trava.

### 3.5. Encerramento por SIGTERM

**Prioridade: bloqueador operacional. Responsável sugerido: desenvolvimento.**

O `main.py` trata explicitamente `KeyboardInterrupt`, mas não SIGTERM.

Ajustes:

- Tratar o sinal de encerramento do provedor.
- Interromper a espera de forma responsiva e impedir o início de novos ciclos.
- Concluir ou reverter a unidade de trabalho dentro do prazo de encerramento.
- Fechar conexão e liberar a trava em `finally`.

**Critério de aceite:** enviar SIGTERM durante espera e ingestão termina o processo dentro do prazo definido; reiniciar retoma a leitura sem checkpoint à frente dos dados duráveis.

### 3.6. Paginar Firebase e limitar memória

**Prioridade: bloqueador de capacidade. Responsável sugerido: desenvolvimento.**

As páginas SQL de 500 não limitam o download Firebase: `consulta.get()` ainda pode carregar todo o backlog por equipamento, e os objetos normalizados são acumulados em memória.

Ajustes:

- Definir páginas de leitura Firebase e lotes de processamento limitados.
- Tratar corretamente a fronteira inclusiva entre páginas, sem loop infinito nem perda de registros.
- Avançar o checkpoint apenas após persistir os dados/rejeições correspondentes.
- Medir primeira carga, recuperação de backlog e operação normal.

**Critério de aceite:** histórico maior que uma página é ingerido integralmente, com memória limitada e retomada segura após falha entre páginas.

### 3.7. Monitoramento e alertas

**Prioridade: bloqueador operacional. Responsáveis sugeridos: desenvolvimento e operação.**

Ajustes:

- Registrar identificador e duração do ciclo, recebidos, inseridos, duplicatas e rejeições.
- Manter heartbeat e último resultado operacional, distinguindo sucesso, falha parcial e falha total.
- Alertar ausência de ciclos bem-sucedidos, falhas consecutivas e crescimento de rejeições.
- Medir atraso de ingestão com uma definição de tempo aprovada.
- Definir retenção/exportação de logs e evitar payloads ou segredos nas mensagens.

O `updated_at` do checkpoint não substitui heartbeat: pode permanecer antigo simplesmente porque não chegaram novas leituras. Equipamento sem dados também não deve ser confundido automaticamente com falha do worker.

**Critério de aceite:** simular banco indisponível, erro parcial e ciclo vazio gera os sinais esperados; um processo vivo com ingestão quebrada dispara alerta.

### 3.8. Imagem, dependências, CI e segredos

**Prioridade: bloqueador de deploy. Responsáveis sugeridos: desenvolvimento e infraestrutura.**

Ajustes:

- Criar Dockerfile com versão Python validada e execução sem privilégios.
- Criar `.dockerignore` excluindo `.env`, credenciais, `.git`, `.venv` e caches.
- Validar instalação de `requirements.txt` em ambiente limpo e sua codificação para as ferramentas utilizadas.
- Executar testes offline e build no CI; executar integração somente em ambiente de teste autorizado.
- Separar CI de CD: mudanças no banco de produção pertencem à etapa de deploy descrita no item 3.9, não aos testes de CI.
- Implantar imagem identificável por commit e manter procedimento de rollback.
- Documentar configuração de deploy como código, sem segredos.
- Montar o JSON Firebase como secret file com caminho absoluto em `FIREBASE_CREDENTIALS`.
- Aplicar privilégio mínimo no Firebase e PostgreSQL; separar usuário de migração do usuário de ingestão.
- Verificar histórico de exposição e rotacionar credenciais comprometidas.

O `.gitignore` protege o versionamento futuro, mas não remove segredos do histórico nem impede inclusão em uma imagem Docker.

**Critério de aceite:** build reproduzível, CI bloqueia testes com falha, imagem não contém segredos e rollback para versão compatível é demonstrado.

### 3.9. Banco, migrações, fuso e restauração

**Prioridade: bloqueador de dados. Responsáveis sugeridos: DBA e desenvolvimento.**

**Situação atual:** `app/sql/schema.sql` é uma entrada para `psql` que inclui
as migrações 000 (base), 001 (rejeições), 002 (identidade por equipamento) e
003 (schema privado/permissões). Após a transferência, a entrada reaplica somente
003 e 004 (instantes `TIMESTAMPTZ`) para não recriar cópias públicas;
não há histórico automático de versões.
As definições existem apenas nas migrações; a sequência atende banco vazio
ou existente. O worker não executa esses scripts ao iniciar. Histórico automático
de versões e integração ao deploy continuam pendentes.

Ajustes:

- Validar versão PostgreSQL, migrações e índices em homologação no Supabase.
- Versionar e executar migrações como etapa controlada, fora do loop ETL.
- Origem confirmada pelo responsável: `America/Sao_Paulo`, inclusive no histórico.
  Parser com fuso e migração 004 para `TIMESTAMPTZ` implementados; validar no Supabase.
- Preservar regras históricas de horário de verão e revisar horas ambíguas/inexistentes
  antes da migração, que aborta em vez de escolher um instante.
- Dimensionar armazenamento, índices e retenção com recursos PostgreSQL.
- Definir RPO (perda máxima tolerada) e RTO (tempo máximo de recuperação).
- Configurar backups e testar restauração conjunta de dados e checkpoints.

#### Migrações no CI/CD — implementação pendente

Fluxo previsto: **CI (testes e build) → CD (migrações pendentes) → disponibilização da nova versão do ETL**.

- **Inicialização de banco novo:** executar `app/sql/schema.sql` em PostgreSQL puro, em etapa controlada com o usuário de migração. Não repetir esse bootstrap a cada deploy.
- **Atualização de banco existente:** executar somente as migrações versionadas pendentes, antes de disponibilizar a versão que depende delas. Implementar histórico de versões aplicadas no banco, para que repetir o deploy não reaplique migrações concluídas.
- **Falha de migração:** interromper o deploy e não disponibilizar a nova versão. Serializar migrações concorrentes e validar compatibilidade com a versão anterior durante a troca.
- **Render Cron escolhido:** prever uma etapa dedicada de CD para executar migrações antes de ativar a nova versão do job; não presumir suporte ao Pre-deploy Command disponível para Workers pagos.
- **Credenciais:** disponibilizar o usuário de migração somente na etapa autorizada de CD, separado do usuário de ingestão com privilégios mínimos. Testes de CI não devem alterar o banco de produção.

**Aceite do CD:** demonstrar em homologação a criação da tabela em banco existente, a ausência de reaplicação em deploy repetido e o bloqueio da nova versão quando uma migração falhar. Essa automação ainda não está implementada.

Um checkpoint restaurado à frente dos dados pode impedir a recuperação de leituras ausentes. Se o Firebase tiver retenção curta, ele não poderá ser presumido como fonte eterna de replay.

**Critério de aceite:** migração e restauração são demonstradas em ambiente isolado; datas preservam o instante esperado; procedimento documenta recuperação sem pular dados.

### 3.10. Rede, plano e ensaio de carga

**Prioridade: bloqueador de liberação. Responsáveis sugeridos: infraestrutura e operação.**

Ajustes:

- Confirmar localização e acessibilidade do banco antes de selecionar a região do worker.
- Validar DNS, IPv4/IPv6, pooler, allowlists e portas necessárias: HTTPS para Firebase/autenticação e conexão PostgreSQL no endpoint escolhido.
- Não pressupor que dois serviços no mesmo provedor estejam automaticamente em rede privada.
- Medir CPU, RSS, duração, tráfego Firebase, crescimento do banco e conexões.
- Testar volume diário representativo, maior backlog esperado e falhas de rede.
- Definir orçamento completo: worker, banco, backups, tráfego e eventual plano de equipe.

Custos e capacidade candidatos foram atualizados na [ADR](adr-hospedagem.md): cron de 512 MB por US$ 0,00016/minuto, mínimo de US$ 1/mês por job. Em 30 dias com 1–2 horas/dia, ambos os cenários ficam no mínimo de US$ 1 de compute. Banco, workspace e demais adicionais não estão incluídos; confirmar antes da contratação.

**Critério de aceite:** equipe aprova limites de memória, duração, atraso, disco e orçamento com base nas medições, não somente em testes unitários.

## 4. Ordem sugerida de execução

1. Confirmar volume, retenção, SLA, orçamento, contrato das chaves e localização do banco.
2. Resolver rejeições, reconciliação, concorrência e política de fuso.
3. Implementar conexões robustas, SIGTERM e paginação.
4. Preparar imagem, segredos, migrações e CI.
5. Implantar homologação e configurar observabilidade.
6. Executar testes reais, carga, interrupção, replay, rollback e restauração.
7. Registrar resultados, responsáveis e aprovação antes de liberar produção.

## 5. Checklist de liberação

- [ ] Plataforma, região, banco, orçamento e responsáveis definidos.
- [ ] Rejeições duráveis e reprocessamento validados.
- [ ] Ordenação das chaves e estratégia para atrasos/backfill aprovadas.
- [ ] Trava entre processos testada, inclusive após reconexão.
- [ ] TLS, timeouts e tentativas de recuperação validados.
- [ ] SIGTERM e retomada após encerramento abrupto testados.
- [ ] Paginação e uso de memória aprovados com backlog representativo.
- [ ] Alertas de ingestão e heartbeat funcionando.
- [ ] Imagem sem segredos, CI e rollback demonstrados.
- [ ] Migrações PostgreSQL no Supabase e política de fuso validadas.
- [ ] Executor de migrações com histórico integrado ao CD, usuário separado e bloqueio de deploy em caso de falha.
- [ ] Backups e restauração conjunta de dados/checkpoints testados.
- [ ] Capacidade, retenção, RPO e RTO aprovados.

## Referências

- [ADR de hospedagem — Render Cron](adr-hospedagem.md)
- [Render Cron Jobs](https://render.com/docs/cronjobs)
- [Render: variáveis de ambiente e secret files](https://render.com/docs/configure-environment-variables)
- [Render: preços](https://render.com/pricing)
- [Supabase: conexão PostgreSQL](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [README](../README.md)
- [Testes](TESTING.md)
