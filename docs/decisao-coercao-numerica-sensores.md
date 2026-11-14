# Decisão — Coerção numérica e validação de sanidade dos sensores

- **Data:** 2026-11-14
- **Status:** implementado
- **Escopo:** `app/transformer/normalize.py`, `tests/test_normalize.py`
- **Item relacionado:** P0 do [`TODO.md`](TODO.md) — “Add numeric coercion + validation
  for sensors”

## Contexto

As leituras de boia já passavam por `_to_float` antes de virar um objeto `Buoy`.
As leituras de sensor, porém, eram copiadas do Firebase sem nenhuma conversão:
`normalize_sensor` apenas montava o dicionário e repassava os valores para
`Sensor(**normalized)`.

Com o schema atual, os valores observados em `sensores/EST002` são numéricos
(`int`/`float`), então a ingestão funciona. O problema é de robustez: qualquer
valor vazio, texto malformado, `NaN`/`Inf` ou booleano chegaria ao psycopg2 e
viraria erro de banco (ou dado inválido gravado), em vez de um erro de
normalização claro, contabilizado por registro.

## Problema

Sem coerção explícita, os seguintes casos não têm tratamento definido:

| Entrada | Comportamento anterior | Risco |
| --- | --- | --- |
| `""` / `"   "` | String vazia enviada ao banco | Erro de cast para `double precision` |
| `"28,5"` | String com vírgula decimal | Erro de cast; formato ambíguo |
| `"nan"`, `"inf"` | `float()` aceita | `NaN`/`Infinity` gravados |
| `True` / `False` | `True` vira `1.0` silenciosamente | Valor sem sentido físico |
| `"abc"` | Erro genérico de cast no banco | Mensagem sem o nome do campo |
| Campo ausente | `Sensor` usa `None` | OK, mas sem validação explícita |

## Decisão

### 1. Um único conversor para sensores e boias

A função `_to_float(value, field)` passou a ser compartilhada pelos dois fluxos.

Regras de conversão:

- `None`, string vazia ou string só com espaços → `None`;
- `int`/`float` → `float`;
- string numérica (ponto decimal) → `float`;
- booleano → `ValueError` (não é grandeza física);
- string inválida, `NaN`, `+Inf`, `-Inf` → `ValueError`;
- tipo não numérico (lista, dicionário etc.) → `ValueError`.

Toda mensagem de erro inclui o nome do campo, por exemplo:

```text
Campo 'temperatura' com valor numérico inválido: '28,5'
```

### 2. Coerção aplicada a todos os campos numéricos do sensor

`SENSOR_NUMERIC_FIELDS`: `ar`, `chuva`, `gas`, `luz`, `pressao`, `rpm`,
`temperatura`, `umidade`, `vento`, `volt`.

Campos ausentes na leitura resultam em `None`, preservando o comportamento dos
modelos (`Sensor` já define `None` como padrão).

### 3. Validação de sanidade (não de calibração)

Foram adotadas apenas regras universalmente defensáveis, sem inventar faixas
dependes de unidade/calibração:

| Regra | Campos |
| --- | --- |
| Não pode ser negativo | `ar`, `chuva`, `gas`, `luz`, `pressao`, `rpm`, `umidade`, `vento`, `volt` |
| Máximo 100 | `umidade` (percentual) |
| Pode ser negativo | `temperatura` (apenas exige valor finito) |
| Sem teto definido | demais campos, até confirmação de unidade/calibração |

`pressao` foi incluída em “não negativo” porque a leitura representa pressão
atmosférica absoluta (a amostra atual é `1009.37`, compatível com hPa). Se o
firmware passar a enviar pressão manométrica (que pode ser negativa), a regra
precisa ser revista.

### 4. Boias: coerção sim, validação de faixa não (por enquanto)

A coerção passou a usar o mesmo `_to_float` (com nome do campo nas mensagens),
mas **nenhuma validação de faixa foi aplicada às boias**. Motivo objetivo: todos
os 9.292 registros atuais têm `ph = 22.84`, valor fisicamente impossível (pH
válido é 0–14). Aplicar `0 <= ph <= 14` agora faria 100% das boias falharem na
normalização e voltaria a zerar a ingestão.

A decisão sobre `ph` inválido (quarentena, descarte, correção na origem ou
manutenção do valor bruto) é um item de qualidade de dados do P2 e precisa ser
tomada com a equipe de firmware/domínio.

## Comportamentos resultantes

```python
# strings numéricas viram float
{"temperatura": "27.69"} -> 27.69

# vazio/ausente vira None
{"umidade": ""} -> None
{} (campo ausente)   -> None

# casos rejeitados com ValueError e nome do campo
{"temperatura": "28,5"}
{"pressao": "nan"}
{"luz": True}
{"rpm": -1}
{"umidade": 100.1}
```

Quando a validação falha, o `ETLWorker` já trata o erro por registro
(`app/worker/etl_worker.py`): incrementa `erros`, registra o motivo e continua o
ciclo, sem gravar aquela leitura.

## Arquivos alterados

- `app/transformer/normalize.py`
  - `_to_float` reescrito com contexto de campo e checagem de finitude;
  - `_validate_sensor_value` adicionada;
  - listas `SENSOR_NUMERIC_FIELDS`, `BUOY_NUMERIC_FIELDS`, `NON_NEGATIVE_FIELDS`
    e `MAX_VALUE`;
  - `normalize_sensor` agora converte e valida todos os campos numéricos;
  - `normalize_buoy` passou a reutilizar a mesma coerção em laço.
- `tests/test_normalize.py`
  - novos casos para strings numéricas, vazios/ausentes, vírgula decimal,
    `NaN`/`Inf`, booleano, valores negativos, umidade acima de 100, temperatura
    negativa permitida e boia com número inválido.

## Validação

Testes offline:

```bash
python -m compileall -q app tests
python -m unittest tests.test_mapper tests.teste_timestamp tests.test_normalize -v
```

Resultado:

```text
Ran 21 tests in 0.003s
OK
```

Verificação somente leitura contra o Firebase real (sem gravar no banco):

```text
sensores: OK=1     FAIL=0
boias:    OK=9292  FAIL=0
```

Nenhuma escrita foi feita no PostgreSQL.

## Limitações e próximos passos

1. **Faixas reais dependem de unidade/calibração.** Os limites atuais são
   sanidade conservadora. Confirmar com firmware/domínio antes de endurecer
   (`temperatura`, `pressao`, `luz`, `gas`, `ar`, `vento`, `rpm`, `volt`).
2. **Política para `ph = 22.84`.** Definir se valores fora de faixa devem ser
   rejeitados, quarentenados ou mantidos com flag de qualidade.
3. **Vírgula decimal é rejeitada de propósito.** `"28,5"` é ambíguo entre
   separador decimal e de milhar; a origem deve enviar número JSON ou ponto
   decimal. Se o firmware usar vírgula, a conversão precisa ser explícita e
   testada.
4. **Validação não substitui calibração.** O objetivo é impedir valores
   claramente impossíveis, não corrigir escala ou offset.
5. **Verificação ponta a ponta ainda pendente.** O banco `moringa` está
   acessível e possui TimescaleDB, mas as tabelas `sensor_data`/`buoy_data` não
   existem; é necessário aplicar `app/sql/schema.sql` em um banco de teste antes
   de executar um ciclo completo.
