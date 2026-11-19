# ADR — Render Cron para atualização diária do ETL

**Data:** 16/11/2026. **Decisão:** adotar Render Cron no recorte inicial, substituindo a proposta de Background Worker contínuo. Implantação condicionada aos ajustes e testes abaixo; nada contratado ou implantado.

**Atualização (18/11/2026):** destino definido como PostgreSQL puro do Supabase,
sem extensão adicional; validar conexão, permissões e capacidade antes do deploy.

## Decisão e execução

Usar **um Render Cron Job**, em imagem Docker por commit, com **`0.5c-512mb` (0,5 CPU, 512 MB RAM)**. Atualização diária aceita pelo usuário; agenda proposta **`0 3 * * *` — 03:00 UTC**, a confirmar.

Comando previsto: **`python -u -m app.run_once`** no `CMD`/Docker Command. **Módulo ainda inexistente:** deverá chamar `ETLWorker.run_once()`, fechar conexões e sinalizar falhas operacionais por código não zero. Rejeição persistida é classificação concluída.

Não agendar `app.main`, cujo loop não termina. **1–2 horas/dia são estimativa**, não espera obrigatória: encerrar ao terminar os pendentes.

## Onde fica cada componente

| Componente | Local |
| --- | --- |
| Código, testes e migrações | GitHub; imagem Docker identificada por commit, ainda a preparar |
| Processo Python | Instância temporária do Render Cron em cada execução |
| Dados de origem | Firebase Realtime Database |
| Medições, rejeições e checkpoints | PostgreSQL do Supabase; backups e acesso a configurar |
| Exclusividade | Advisory lock na mesma sessão PostgreSQL dos repositórios |
| Segredos e logs | Configuração/secret files do Render e coleta de stdout/stderr |

**Cron não oferece disco persistente.** Nenhum progresso pode depender de arquivo local; checkpoints e rejeições ficam no banco. A credencial montada em secret file é configuração, não estado.

## Evidência de capacidade inicial

Levantamento de **16/11/2026**, com dados reais:

| Item | Resultado |
| --- | --- |
| Firebase | **9.293 leituras**: EST002 = 1; BOIA001 = 9.291; BOIA002 = 1 |
| PostgreSQL de teste | **9.293 medições**, banco completo com **13,365 MiB** |
| RAM antes do ciclo | Aproximadamente **56 MiB** |
| RAM na carga histórica completa | Pico RSS de **69,555 MiB**, arredondado para **70 MiB** |
| RAM no incremental | Aproximadamente **61 MiB**; nenhum registro novo nos checkpoints consultados |

A medição local usou Python **3.14.4**, leitura/normalização reais e montagem SQL, **sem inserts ou alteração de checkpoints**. A carga histórica levou **2,54 segundos nessa simulação**, não em ingestão completa no Render.

70 MiB são cerca de 73 MB decimais: **14% dos 512 MB anunciados**. Margem favorável à homologação, não aprovação de produção: medir CPU, inserts e RAM no container. O backlog ainda pode ficar inteiro em memória; crescimento futuro não foi validado.

## Motivos e custos

Cron elimina compute ocioso entre atualizações, reduzindo custo frente ao Worker de US$ 7/mês e administração frente a VM/Kubernetes. Contrapartidas: inicialização por rodada e atraso dos dados. Docker mantém portabilidade.

Preços públicos consultados em **16/11/2026**: **US$ 0,00016/minuto ativo**, proporcional por segundo, com mínimo de **US$ 1/mês por cron job**.

| Cenário em 30 dias | Tempo ativo | Cálculo | Compute cobrado |
| --- | --- | --- | --- |
| 1 hora/dia | 1.800 minutos | US$ 0,288 | **US$ 1/mês** |
| 2 horas/dia | 3.600 minutos | US$ 0,576 | **US$ 1/mês** |

Economia: **US$ 6/mês (~86%)** frente ao Worker. Exclui banco, Firebase, excedentes, imagens/builds, impostos/câmbio. Hobby tem um assento; workspace Pro adiciona US$ 25/mês: **cron + workspace = US$ 26**, sem banco.

## Rede e operação

- **Região:** confirmar a mais próxima do banco, considerando Firebase/residência dos dados. Render não lista Brasil.
- **IPv4/IPv6:** Render exige saída IPv4. Validar DNS/allowlist dos CIDRs regionais. Supabase: **shared pooler session, porta 5432**, host/usuário do painel; conexão direta padrão é IPv6, salvo add-on IPv4. Nunca transaction, incompatível com a trava.
- **TLS/segredos:** HTTPS/443 no Firebase; PostgreSQL com CA/hostname (`sslmode=verify-full`). Provisionar `POSTGRES_*`, `FIREBASE_DATABASE_URL` e secret file com `FIREBASE_CREDENTIALS=/etc/secrets/firebase_key.json`, fora do Git/imagem. Validar TLS, timeouts e acesso sem root.
- **Logs:** stdout/stderr sem credenciais/payloads; Hobby retém 7 dias, Pro 14. Rejeições ficam no banco. Alertar falha ou ausência de sucesso diário.
- **Limites/retomada:** máximo **12 horas/rodada**, uma execução do job por vez; atraso adia a próxima. Disparo manual cancela a ativa. Não presumir retry automático: próxima execução retoma checkpoints. Manter trava contra outros processos e implementar SIGTERM/encerramento seguro.
- **CD:** migrações antes de promover o job, com histórico, usuário separado e bloqueio em falha; não presumir Pre-deploy Command de Worker para Cron. Ver [preparacao-producao.md](preparacao-producao.md).

## Supabase atende ao recorte inicial?

**Capacidade candidata, não aprovada.** Free: 500 MB de banco, CPU compartilhada/até 0,5 GB RAM, 5 GB egress, pausa após uma semana inativo e sem backups automáticos. Pro: a partir de US$ 25/mês, 8 GB disco, 250 GB egress, créditos para um Micro (1 GB RAM). Nano/Micro: 60 conexões DB/200 clientes pooler; o ETL usa uma sessão, sujeito ao saldo dos demais clientes.

Os **13,365 MiB do banco de teste**, não da conta Supabase, indicam volume pequeno frente a 500 MB. Não validam crescimento, rejeições, egress, CPU ou retenção no serviço. RAM do banco é separada da RAM do cron.

**Banco definido:** schema e migrações usam PostgreSQL puro, sem dependência de
extensão. Testes locais em PostgreSQL 16 não substituem a validação de TLS,
pooler em modo session, permissões e desempenho no Supabase.

Cron + Supabase Free: referência **US$ 1/mês**; com Pro/Micro, **US$ 26/mês**, sem workspace Render Pro/extras e **condicionados à compatibilidade**, não contratação aprovada.

## Alternativa somente se Render não for viável

Se orçamento, rede, região ou capacidade inviabilizarem Render, executar a mesma imagem de execução única em **VM Linux com systemd timer diário em UTC**, próxima do banco ou na rede institucional. Manter estado externo, trava, TLS e segredos; a equipe assume manutenção e supervisão. Não presumir VM gratuita. Trocar executor não resolve incompatibilidade do banco.

## Fontes consultadas

- Render: [Cron e limites](https://render.com/docs/cronjobs), [preços](https://render.com/pricing), [regiões](https://render.com/docs/regions), [rede IPv4](https://render.com/articles/how-to-connect-a-render-service-to-supabase-postgres).
- Supabase: [preços](https://supabase.com/pricing), [compute e conexões](https://supabase.com/docs/guides/platform/compute-and-disk), [conexão/TLS](https://supabase.com/docs/guides/database/connecting-to-postgres).
