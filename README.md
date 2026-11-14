# Orders API

Este es un proyecto pequeño en Python sobre datos de pedidos sintéticos:

1. Genera un CSV de pedidos con errores a propósito: duplicados, fechas mal escritas e importes vacíos.
2. Limpia el CSV y lo carga en SQLite con dos vistas: ventas mensuales por país y los 10 mejores clientes.
3. Ofrece un endpoint que recibe una pregunta en lenguaje natural. Un LLM escribe el SQL. La API
   valida ese SQL, lo ejecuta en modo de solo lectura y devuelve el resultado.

## Cómo ejecutar

Necesitas [uv](https://docs.astral.sh/uv/). uv instala Python 3.13 si no lo tienes.

```bash
uv sync                          # instala las dependencias
uv run generate                  # crea data/orders_raw.csv (1.260 filas, semilla fija)
uv run etl                       # limpia el CSV y crea data/orders.db con las vistas
cp .env.example .env             # escribe tu OPENROUTER_API_KEY en .env
uv run --env-file .env serve     # API en http://127.0.0.1:8000/docs
```

`--env-file` es necesario porque PydanticAI lee la clave del proveedor desde el entorno del
proceso. Las demás variables opcionales y sus valores por defecto están en `.env.example`. Por
ejemplo, `LLM_MODEL` cambia el modelo y `QUERY_TIMEOUT` cambia el tiempo máximo de una consulta.

### Ejemplo

```bash
curl -s http://127.0.0.1:8000/v1/completion \
  -H 'Content-Type: application/json' \
  -d '{"question": "¿Cuánto vendimos en España en marzo?"}'
```

```json
{
  "question": "¿Cuánto vendimos en España en marzo?",
  "sql": "SELECT orders_count, total_amount FROM monthly_sales_by_country WHERE country = 'España' AND month = '2025-03' LIMIT 500",
  "columns": ["orders_count", "total_amount"],
  "rows": [[7, 10334.51]]
}
```

`sql` es la consulta validada que se ejecutó. El SQL puede variar entre llamadas, porque lo escribe
el modelo. Si la pregunta no se puede responder con los datos, la API da un error claro y no
inventa filas:

```json
{"detail": {"code": "unanswerable", "message": "No puedo responder sobre el tiempo en Madrid. Solo tengo acceso a datos de pedidos de ventas (pedidos, ventas mensuales por país y mejores clientes), que no incluyen información meteorológica."}}
```

### Errores

| Caso | HTTP | `code` |
|---|---|---|
| Cuerpo inválido (pregunta vacía o de más de 500 caracteres) | 422 | validación de FastAPI |
| El LLM no responde, da timeout o un error de API | 502 | `llm_unavailable` |
| El LLM devuelve una salida inválida (texto en lugar de SQL, SQL vacío) | 502 | `llm_invalid_output` |
| Los datos no responden la pregunta, o el filtro del proveedor la bloquea | 422 | `unanswerable` |
| El validador rechaza el SQL | 422 | `unsafe_query` |
| SQLite rechaza el SQL, la consulta pasa el tiempo máximo o un límite de tamaño | 422 | `query_failed` |

Los errores 502 son fallos del proveedor del LLM. Los errores 422 dependen de la pregunta.

### Tests y calidad

```bash
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q
```

Hay 65 tests y ninguno usa la red. Un `FunctionModel` de PydanticAI simula el LLM, así que el
agente real y el mapeo de errores corren en cada test. `ALLOW_MODEL_REQUESTS = False` hace
fallar cualquier llamada real a un proveedor.

- `test_cleaning.py`: cada formato de fecha y cada motivo de descarte. También comprueba el dataset generado completo.
- `test_sql_guard.py`: las consultas aceptadas, con el SQL reescrito exacto, y cada tipo de rechazo con su motivo.
- `test_api.py`: el endpoint con una base pequeña. Comprueba cada código de error y el evento de log.

## Estructura

```
src/
  constants.py, config.py, errors.py
  pipeline/   generate.py (Faker) · cleaning.py (polars, puro) · etl.py
  db/         schema.sql · views.sql · loader.py (escritura) · reader.py (solo lectura)
  query/      sql_guard.py (validador) · sql_generator.py (agente PydanticAI)
  api/        app.py (raíz de composición) · v1/completion.py · v1/schemas.py
tests/
```

`app.py` crea todas las dependencias y las inyecta en el router. No hay clientes globales.

## Decisiones

**Datos y limpieza**

- **SQLite.** Es más rápido y fácil para una prueba: no necesita un servidor y viene con Python.
  También tiene vistas y conexiones de solo lectura. En producción usaría PostgreSQL con un rol de
  solo lectura y `statement_timeout`.
- **Polars en lugar de pandas.** Es más rápido y lee el CSV con un esquema estricto: todas las
  columnas son texto, así que una cabecera incorrecta falla de inmediato. También es la
  herramienta que prefiero. La limpieza usa solo expresiones de polars, sin bucles por fila.
- **Datos deterministas.** Faker (`es_ES`) usa la semilla 42. La misma semilla da un CSV idéntico
  byte a byte.
- **Fechas.** La limpieza acepta el formato ISO primero y después formatos con el día primero
  (`31/01/2025`). Los países son hispanohablantes, así que `03/04/2025` es el 3 de abril. Una
  fecha imposible (`31/02/2025`) se descarta.
- **Duplicados.** Se quitan *después* de validar. Así una primera copia inválida no oculta una
  copia válida posterior.
- **Resultado.** De 1.260 filas se cargan 1.122. Se descartan 51 duplicados, 48 importes
  inválidos, 27 fechas inválidas y 12 estados desconocidos.
- **Ventas = pedidos `completed`.** Las vistas y las instrucciones del LLM usan la misma regla.
- **Top 10 por importe.** `top_customers` ordena por el importe total de ventas, no por el
  número de pedidos. Si hay empate, ordena por nombre.
- **Esquema.** La tabla es `STRICT` y tiene restricciones `CHECK` (fecha ISO, importe > 0,
  estado válido). El ETL crea la base en un archivo temporal y lo cambia de forma atómica, así
  que un lector nunca ve una base a medio construir.

**Seguridad de las consultas**

El SQL del LLM pasa por dos capas. Ninguna consulta se ejecuta sin pasar la primera.

1. **Validador (`sql_guard.py`).** sqlglot analiza el SQL como un árbol (AST), sin usar
   expresiones regulares. Estas son sus reglas:
   - Acepta una sola sentencia `SELECT`. También acepta `WITH` y `UNION`.
   - Busca en todo el árbol operaciones de escritura, DDL, `PRAGMA` y `ATTACH`. Hay que buscar
     en todo el árbol porque sqlglot lee `SELECT … INTO` y un `DELETE` dentro de un CTE como un
     `SELECT`.
   - Solo acepta las tablas permitidas o los CTE visibles en ese punto, con el mismo alcance que
     SQLite. Así un CTE no puede ocultar una tabla del sistema.
   - Exige que la consulta lea al menos una tabla real, para que el modelo no responda con filas
     inventadas.
   - Limita el resultado a 500 filas.
2. **Lector (`reader.py`).** Usa una conexión de solo lectura (`mode=ro`), nueva en cada
   petición. Tiene un tiempo máximo de 5 s y límites de tamaño: 100 KB por valor, 64 columnas y
   5 MB por resultado. `LIMIT` no detiene un producto cartesiano ni un CTE recursivo infinito, y
   `zeroblob()` puede crear un valor enorme en un solo paso.

**LLM**

- **PydanticAI.** No depende de un proveedor: otro modelo es otro valor de `LLM_MODEL` y un extra
  de uv, sin cambios en el código. La salida es tipada y no se parsea texto libre. Los tests no
  usan la red. Para desarrollo y pruebas uso OpenRouter. El modelo por defecto es
  `openrouter:anthropic/claude-sonnet-5.5`, y `LLM_MODEL` lo cambia.
- **Dos salidas posibles.** El modelo devuelve el SQL (`answer_with_sql`) o una razón
  (`cannot_answer`). Antes, sin la segunda salida, el modelo respondía con un `SELECT` de
  literales (por ejemplo, `SELECT 1 AS tablas`). Así la API devolvía 200 con datos inventados.
- **Instrucciones.** Se generan desde `constants.py`, `schema.sql` y `views.sql`. El esquema no
  está copiado a mano.
- **Logs.** structlog registra un *wide event* por petición (`completion_handled`) con la
  pregunta, el SQL, el estado, el código de error y la duración.
- **Nombre del endpoint.** `/v1/completion` solo sigue el estilo de rutas de OpenAI. El cuerpo no
  es el esquema de OpenAI.

## Prueba E2E con el modelo real

Además de pytest, ejecuté un script E2E contra la API con el modelo real. El script no está en
el repositorio, porque los tests no deben llamar a un LLM de pago. Hubo dos ejecuciones: antes y
después de agregar la salida `cannot_answer`. La tabla muestra la segunda, salvo las dos últimas
filas.

| Prueba | Resultado |
|---|---|
| 11 cuerpos inválidos, `GET` y una ruta desconocida | 422, 405 y 404, sin llamar al LLM |
| 12 preguntas de negocio (con tildes y sin ellas, en inglés, con emojis) | 200 con SQL correcto y la regla de ventas aplicada (`peru` → `'Perú'`) |
| Preguntas fuera de los datos: clima, email, año 2023, "¿cuántos?" | 422 `unanswerable`, con la razón del modelo |
| Ataques: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `sqlite_master`, `PRAGMA`, `ATTACH`, `load_extension`, varias sentencias, pedir el prompt | 422 `unanswerable` |
| Self-join triple con `COUNT(*)` | 422 `query_failed` a los 5 s |
| Una cadena enorme hecha con `printf` | 422 `query_failed` (límite de tamaño por valor) |
| `LIMIT 100000` y `LIMIT -1` | 200 con 500 filas |
| 20 peticiones simultáneas (1.ª ejecución) | 20 × 200, con una mediana de 1,6 s |
| El ETL reconstruye la base durante 8 peticiones (1.ª ejecución) | 8 × 200, con el mismo resultado |

En la primera ejecución, el modelo respondía a varios ataques con un `SELECT` de literales (200
con datos inventados). El validador rechazó `pragma_table_info` con `unsafe_query`, y el hash de
`orders.db` no cambió después de los ataques.

## Qué haría con más tiempo

- **Seguridad SQL.** Agregar `set_authorizer` de SQLite como otra capa en la conexión, para
  permitir solo lecturas de las tablas de la lista. Agregar al validador una lista de funciones
  SQL permitidas (ahora acepta `zeroblob`, `randomblob`, …).
- **Observabilidad.** Logs en JSON. Guardar la pregunta con hash, o no guardarla, porque puede
  tener datos personales. Métricas de latencia y de errores por `code`.
- **Calidad del LLM.** Crear *evals*: preguntas con la respuesta esperada, para medir la
  precisión del SQL cuando cambian el modelo o el prompt.
- **Operación.** Docker, un CI con el quality gate, pre-commit, autenticación y rate limit en la
  API. Pasar a PostgreSQL con un rol de solo lectura.

## Uso de IA

<!-- Borrador con hechos. Edítalo con tu voz antes de entregar. -->

- Usé Claude Code como asistente durante todo el proyecto. Trabajamos por fases (scaffold, datos,
  validador, LLM + API, README) y revisé cada fase antes de hacer el commit.
- Primero el asistente generó un `AGENTS.md` con las reglas del proyecto a partir de mis guías:
  estándares de código, stack y comandos.
- Mis decisiones:
  - El asistente propuso `csv` de la librería estándar y el SDK de Anthropic. Los cambié por
    polars y PydanticAI con OpenRouter.
  - Pedí los scripts de uv (`uv run generate`), Faker y una estructura sin un paquete dentro de
    `src/`.
  - Pedí structlog para los logs y el endpoint versionado `/v1/completion`.
- Correcciones que salieron de las revisiones:
  - El validador aceptaba un CTE de una subconsulta como si ocultara una tabla real de la
    consulta exterior. Ahora usa el mismo alcance que SQLite.
  - Una columna BLOB daba un error 500. Ahora la respuesta la envía en base64.
  - `SELECT zeroblob(200000000)` usaba 600 MB de memoria. Ahora el lector tiene límites de
    tamaño.
- La prueba E2E con el modelo real mostró que el modelo inventaba filas con literales. Por eso
  agregué la salida `cannot_answer` y la regla de "al menos una tabla real".
