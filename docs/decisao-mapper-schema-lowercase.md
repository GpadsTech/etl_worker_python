# Decisão — Alinhar o mapper ao schema minúsculo do Firebase

- **Data:** 2026-11-14
- **Status:** implementado
- **Escopo:** `app/transformer/mapper.py`, `app/transformer/timestamp.py`,
  `app/transformer/normalize.py` e testes offline
- **Item relacionado:** P0 do [`TODO.md`](../TODO.md)

## Contexto

O worker ETL lê `/sensores` e `/boias` do Firebase Realtime Database,
normaliza cada leitura em um objeto `Sensor` ou `Buoy` e persiste no
PostgreSQL/TimescaleDB.

O `FieldMapper` funciona como uma tabela de tradução: o normalizador percorre
as chaves recebidas e copia apenas aquelas que existem no mapa. Se a chave não
existe, o campo é descartado silenciosamente.

## Problema

O mapa utilizava nomes capitalizados (`Hora`, `Temperatura`, `Data`,
`Sensor UV(V)`), enquanto os dados reais do Firebase usam chaves minúsculas
(`hora`, `temperatura`, `sensor_uv_v`). Como nenhuma chave coincidia:

- `normalize_sensor` montava um dicionário apenas com `firebase_id` e
  `sensor_id` e falhava em `normalized.pop("timestamp")`
  (`KeyError: 'timestamp'`);
- `normalize_buoy` falhava em `normalized.pop("data")`
  (`KeyError: 'data'`), pois o campo `Data` não existe mais;
- o `ETLWorker` capturava cada exceção, incrementava `erros` e seguia o ciclo,
  produzindo `Recebidos: 9292 / Inseridos: 0 / Erros: 9292` sem interromper o
  processo. O serviço parecia saudável, mas não gravava nada.

## Evidências levantadas (somente leitura)

Levantamento das chaves reais, por equipamento, em 2026-11-14:

| Nó / equipamento | Registros | Chaves presentes |
| --- | ---: | --- |
| `sensores/EST002` | 1 | `ar, gas, hora, luz, pressao, rpm, temperatura, umidade, vento, volt, endereco_ip, identificador` |
| `boias/BOIA001` | 9.291 | `hora, ph, sensor_uv_v, turbidez_v, endereco_ip, identificador` e, em parte, `adc` |
| `boias/BOIA002` | 1 | `adc, hora, ph, sensor_uv_v, turbidez_v, endereco_ip, identificador` |

Conclusões:

1. **100% dos 9.294 registros usam chaves minúsculas.** Nenhum registro
   capitalizado foi encontrado.
2. O campo `Data` não existe mais. Sensores e boias enviam um único `hora` no
   formato `AAAA-MM-DD HH:MM:SS`.
3. `adc` está ausente em 20 dos 9.291 registros de `BOIA001`; precisa continuar
   opcional.
4. `chuva` e `tensao_v` não aparecem nos dados atuais, mas existem no schema do
   banco e podem voltar a ser enviados.

## Decisão

**Adotar somente o schema minúsculo (Opção A).** Os nomes capitalizados foram
removidos do mapa; o formato antigo deixou de ser suportado.

Motivos:

- Não há produtor conhecido emitindo o formato antigo: todos os registros
  atuais são minúsculos.
- Manter as duas variantes criaria ambiguidade se um registro trouxesse as duas
  chaves (a última processada venceria silenciosamente).
- Os testes passavam porque usavam fixtures do formato antigo, mascarando o
  problema. Os testes agora refletem o payload real.
- O código fica menor e a intenção explícita: se um formato legado voltar, ele
  deve ser tratado como um novo requisito, com teste e precedência documentada.

Caso surja um emissor legado, a recomendação é reabrir a decisão e implementar
aliases com precedência explícita e teste para cada variante — não reintroduzir
as chaves antigas sem necessidade comprovada.

## Alterações realizadas

### `app/transformer/mapper.py`

- Chaves de sensor e boia convertidas para minúsculas.
- `hora` mapeado para `timestamp` nos dois tipos.
- Inclusão de `chuva` (sensor) e `tensao_v` (boia), previstos no schema mas
  ausentes nos dados atuais.
- Docstring registra que `endereco_ip` e `identificador` são metadados
  descartados intencionalmente e que o formato capitalizado não é suportado.

### `app/transformer/timestamp.py`

- Formato único `AAAA-MM-DD HH:MM:SS` centralizado em `TIMESTAMP_FORMAT`.
- `buoy_timestamp` passou a receber **um único valor** (`hora` completo), em vez
  de `data` + `hora`.
- As duas funções foram mantidas separadas para preservar a intenção de domínio
  de cada origem.

### `app/transformer/normalize.py`

- `normalize_buoy` agora faz `normalized.pop("timestamp")` e chama
  `buoy_timestamp(value)`.

### Testes

- `tests/test_mapper.py`: valida as chaves minúsculas e garante que as antigas
  não estão mais mapeadas.
- `tests/test_normalize.py`: fixtures no formato real; cobre sensor, boia,
  `adc` ausente, metadados descartados, conversão numérica e valores vazios.
- `tests/teste_timestamp.py`: cobre `hora` único e rejeita o formato antigo
  `DD/MM/AAAA HH:MM:SS`.

## Comportamento após a mudança

- Campos mapeados são copiados; chaves desconhecidas continuam sendo ignoradas
  (comportamento explícito para metadados).
- `adc` e `tensao_v` permanecem opcionais e resultam em `None` quando ausentes.
- Leituras com `hora` inválido continuam gerando erro por registro, contado em
  `erros` — o que agora representa uma falha real de dados, não um schema
  desalinhado.
- **Fora do escopo desta mudança:** conversão numérica dos sensores, validação
  de faixas, uso de `TIMESTAMPTZ` e atualização do README. Esses itens seguem no
  `TODO.md` (P0 restante e P2).

## Validação

Testes offline:

```bash
python -m compileall -q app tests
python -m unittest tests.test_mapper tests.teste_timestamp tests.test_normalize -v
```

Resultado:

```text
Ran 12 tests in 0.003s
OK
```

Verificação somente leitura contra o Firebase real (sem gravar no banco):

```text
sensores: OK=1     FAIL=0
boias:    OK=9292  FAIL=0
```

Todos os registros atuais passaram a normalizar com sucesso. Nenhuma escrita foi
feita no PostgreSQL durante a validação.

## Riscos e mitigação

| Risco | Mitigação |
| --- | --- |
| Algum emissor antigo ainda envie chaves capitalizadas | Monitorar `erros` no ciclo; se aparecer `KeyError: 'timestamp'`, reabrir a decisão e implementar aliases com precedência explícita |
| Campos novos enviados pelo firmware sejam descartados em silêncio | Registrar/whitelistar chaves desconhecidas em um passo futuro (observabilidade) |
| Testes de integração ainda usam `EST001` e o schema antigo | Item P2 do `TODO.md`: remover IDs fixos e separar testes unitários de integração |

## Próximos passos

1. Implementar conversão numérica dos sensores (P0 restante).
2. Validar um ciclo completo contra um banco de teste (P0).
3. Atualizar o README, que ainda documenta o schema capitalizado e a divisão
   `Data` + `Hora` (P2).
4. Renomear `tests/teste_timestamp.py` para `tests/test_timestamp.py` (P2).
5. Revisar os testes de integração que fixam `EST001` (P2).
