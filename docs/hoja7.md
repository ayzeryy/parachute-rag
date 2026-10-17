# Hoja de trabajo 7: guía técnica y de ejecución

## 1. Objetivo y alcance

La Hoja 7 convierte la composición centralizada de Parachute S.A. en una
integración interoperable de dos fronteras:

- A2A expone un único agente externo para FAQs y reservas.
- MCP expone las operaciones de FAQ, fecha, clima, seguridad y agenda.

El triaje permanece local al supervisor central asíncrono. Las reglas de
seguridad, los modelos y la persistencia siguen en los servicios de dominio;
los adaptadores de protocolo no mantienen una segunda implementación. Las
arquitecturas locales `centralizada.py`, `jerarquica.py` y
`descentralizada.py` se conservan.

## 2. Arquitectura

```mermaid
flowchart LR
    U[Usuario] --> CLI[Terminal cli_a2a]
    CLI -->|A2A JSON-RPC 1.0 sobre HTTP| A2A[Servidor A2A]
    A2A --> EX[ParachuteA2AExecutor]
    EX --> SUP[MCPAsyncCentralSupervisor]
    SUP -->|Triaje local| TRI[TriageAgent]
    SUP --> GW[RemoteMCPToolGateway]
    GW -->|MCP Streamable HTTP| MCP[Servidor MCP único]
    MCP --> DOM[DomainToolGateway]
    DOM --> FAQ[FAQs]
    DOM --> DATE[Fecha]
    DOM --> WEATHER[Clima]
    DOM --> SAFE[Seguridad]
    DOM --> DB[(Agenda SQLite)]
```

Cada solicitud A2A crea su propio `RemoteMCPToolGateway`, descubre las
herramientas, ejecuta las llamadas de esa solicitud y cierra la sesión. Esto
aísla cliente, experiencia y correlación. Las llamadas de una sesión se
serializan porque el SDK MCP mantiene estado de sesión. No existe respaldo
local silencioso si MCP falla.

## 3. Componentes y responsabilidades

| Componente | Responsabilidad |
|---|---|
| `parachute/cli_a2a.py` | Descubrir la Agent Card con el cliente oficial, enviar texto y datos y presentar categorías. |
| `parachute/a2a_server.py` | Publicar Agent Card y endpoint JSON-RPC A2A. |
| `parachute/a2a_executor.py` | Validar entrada, propagar correlación y adaptar el resultado del supervisor. |
| `parachute/mcp_centralized.py` | Clasificar localmente y coordinar las herramientas remotas. |
| `parachute/mcp_client.py` | Descubrir e invocar MCP por Streamable HTTP y validar contratos. |
| `parachute/mcp_server.py` | Publicar las herramientas, recurso y prompt; adaptar servicios de dominio. |
| `parachute/tool_contracts.py` | Modelos Pydantic serializables y estrictos de la frontera MCP. |
| `parachute/a2a_contracts.py` | Contratos de datos y categorías de la frontera A2A. |
| `parachute/demo.py` | Sustitutos deterministas solo para dependencias externas. |
| `parachute/demo_admin.py` | Mostrar fechas e inspeccionar o reiniciar la SQLite demo marcada. |

## 4. Contrato MCP

El servidor se inicia con `python -m parachute.mcp_server`, escucha por defecto
en `127.0.0.1:8001` y publica Streamable HTTP en `/mcp`. Todas las herramientas
reciben sus argumentos dentro del objeto obligatorio `request`; no se deben
enviar campos al nivel superior.

| Herramienta | Contenido de `request` | Resultado estructurado |
|---|---|---|
| `buscar_faqs` | `query`, `limit` opcional y `correlation_id` opcional | consulta y lista de evidencias con ID, pregunta, respuesta y similitud |
| `extraer_fecha` | `text` y `correlation_id` opcional | `requested_date` ISO |
| `consultar_clima` | `requested_date` y `correlation_id` opcional | temperatura, precipitación, nubes, viento y ráfagas con unidades explícitas |
| `evaluar_seguridad` | objeto `weather` y `correlation_id` opcional | nivel, razones, permiso y requisito de tándem experimentado |
| `crear_cita` | `customer`, `requested_date`, `experienced_tandem` booleano y `correlation_id` opcional | `created`, `rejected` o `duplicate`, evaluación final y cita solo si fue creada |

Ejemplo conceptual de argumentos MCP:

```json
{
  "request": {
    "customer": "Cliente Demo",
    "requested_date": "AAAA-MM-DD",
    "experienced_tandem": false,
    "correlation_id": "id-opaco"
  }
}
```

`crear_cita` no acepta clima ni una aprobación fabricada. Dentro del servidor
vuelve a consultar el clima y aplicar las reglas de dominio antes de persistir;
su decisión es la autoridad final aunque difiera de una evaluación preliminar.
Un fallo meteorológico, datos incompletos o condiciones prohibidas impiden la
escritura.

El recurso `parachute://politicas/seguridad` devuelve Markdown con los umbrales
aplicados. El prompt `consulta_faq` requiere el argumento `pregunta` y guía a
responder solo con evidencia y sus identificadores.

## 5. Contrato A2A y Agent Card

El servidor se inicia con `python -m parachute.a2a_server`, escucha por defecto
en `127.0.0.1:8000`, sirve JSON-RPC 1.0 en `/` y publica el descubrimiento en
`/.well-known/agent-card.json`.

La Agent Card anuncia:

- nombre: `Asistente Parachute S.A.`;
- skills: `consultar_faqs` y `reservar_salto`;
- modos: `text/plain` y `application/json`;
- respuestas directas, sin streaming ni notificaciones push;
- extensión `urn:parachute:runtime-mode:v1` con `real` o `demo`.

Una entrada válida contiene exactamente una parte de texto no vacía de hasta
2000 caracteres y, como máximo, una parte de datos JSON:

```json
{
  "cliente": "Cliente Demo",
  "experienced_tandem": false
}
```

`experienced_tandem` debe ser un booleano real; la cadena `"false"` es
inválida. Si se omite, el valor seguro es `false`. No se infiere experiencia
desde el texto. Una reserva requiere un `cliente` no vacío y sin espacios
externos. Cada mensaje necesita `message_id`; la terminal genera además un
`context_id` único por consulta. Las consultas de una sesión son independientes
y el servidor no promete memoria conversacional.

La respuesta contiene texto y una parte JSON con `category`, `route` y
`correlation_id`. Las categorías son:

| Categoría | Significado |
|---|---|
| `business_result` | FAQ respondida o reserva procesada; el texto distingue creada, rechazada o duplicada. |
| `invalid_input` | Contrato o dato de dominio inválido. |
| `mcp_error` | Error de herramienta, protocolo o contrato MCP. |
| `infrastructure_error` | MCP o una dependencia no están disponibles. |
| `write_outcome_unknown` | La escritura pudo salir, pero se perdió su respuesta. |

Una tarea técnicamente procesada no equivale a una reserva aprobada. Ante
`write_outcome_unknown` no se reenvía automáticamente `crear_cita`: se debe
inspeccionar la agenda antes de reintentar.

## 6. Recorrido de una FAQ

1. La terminal descubre la Agent Card y envía texto y datos con IDs nuevos.
2. A2A valida partes, tipos e identificadores.
3. El triaje local selecciona FAQ.
4. El gateway descubre e invoca `buscar_faqs` por MCP HTTP.
5. El servidor consulta la base correspondiente a la modalidad.
6. El supervisor responde con evidencia y el ID de la ficha, o con el rechazo
   exacto de falta de información.
7. La correlación del mensaje aparece en la respuesta y en los logs A2A/MCP.

## 7. Recorrido de una reserva

1. A2A valida texto, `cliente` y el booleano `experienced_tandem`.
2. El supervisor invoca por MCP `extraer_fecha`, `consultar_clima` y
   `evaluar_seguridad`.
3. Invoca `crear_cita` una sola vez.
4. El servidor MCP vuelve a consultar clima y seguridad.
5. Solo una evaluación final permitida llega al repositorio de citas.
6. La respuesta final distingue creación, rechazo o duplicado.

El rechazo por lluvia, viento, ráfagas, nubes o falta de experiencia requerida
es un resultado normal de negocio. No se confirma una cita si MCP no la
confirmó.

## 8. Seguridad, observabilidad y errores

Las reglas críticas están en `parachute/safety.py`. No dependen de un LLM. El
servidor MCP registra inicio, finalización, duración, resultado y correlación de
cada herramienta; A2A registra recepción, procesamiento, resultado y duración.
Los parámetros registrados se reducen a datos seguros, como longitud de texto,
fecha o presencia de experiencia, sin claves ni texto personal innecesario.

Se distinguen resultados de negocio, errores de herramienta MCP, conexión o
protocolo, contratos incompatibles y escritura incierta. Las herramientas de
lectura pueden informar un fallo controlado; `crear_cita` no se reintenta tras
timeout o pérdida de conexión.

`.env`, `.demo/`, `*.sqlite3`, `*.log` y cachés locales están excluidos de Git.
Los reportes de Promptfoo en `output/` sí son entregables versionados. Nunca se
deben copiar credenciales a comandos, logs, capturas o documentación.

## 9. Configuración

| Variable | Valor predeterminado | Uso |
|---|---|---|
| `PARACHUTE_MODE` | `real` | Selección explícita `real`/`demo`; no cambia automáticamente. |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8001` | Escucha del servidor MCP. |
| `MCP_SERVER_URL` | `http://127.0.0.1:8001/mcp` | Cliente MCP dentro de A2A. |
| `MCP_TIMEOUT_SECONDS` | `10` | Apertura e invocaciones MCP. |
| `A2A_HOST` / `A2A_PORT` | `127.0.0.1` / `8000` | Escucha del servidor A2A. |
| `A2A_SERVER_URL` | `http://127.0.0.1:8000` | URL anunciada y valor de la terminal. |
| `LOG_LEVEL` | `INFO` | Nivel de logs de servidores. |
| `DEMO_APPOINTMENTS_DB` | `.demo/appointments.demo.sqlite3` | SQLite marcada de demo; debe terminar en `.demo.sqlite3`. |
| `DEMO_CORPUS_PATH` | `Corpus_FAQs_Parachute_SA_2026.txt` | Corpus versionado para búsqueda léxica demo. |
| `APPOINTMENTS_DB` | `appointments.sqlite3` | SQLite del modo real. |
| `DATABASE_URL` | PostgreSQL local de `.env.example` | FAQs reales con pgvector. |

La ruta demo no puede coincidir con `APPOINTMENTS_DB`. La Agent Card muestra el
modo del proceso A2A, no una certificación remota del modo MCP. Configure
`PARACHUTE_MODE` explícitamente en ambos servidores y verifique que ambos logs
de arranque indiquen `MODO DEMO` o `REAL` según corresponda.

## 10. Demostración local en tres terminales

Desde la raíz del repositorio, prepare una vez el entorno:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
```

No coloque secretos reales en `.env` para la demo. Consulte primero las fechas
relativas; copie de la salida las fechas `ideal`, `prohibido`,
`viento_marginal` y `nubes_marginales`:

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
$env:DEMO_CORPUS_PATH='Corpus_FAQs_Parachute_SA_2026.txt'
.\.venv\Scripts\python.exe -m parachute.demo_admin dates
```

### Terminal 1 — MCP

```powershell
$env:PARACHUTE_MODE='demo'
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
$env:DEMO_CORPUS_PATH='Corpus_FAQs_Parachute_SA_2026.txt'
$env:MCP_HOST='127.0.0.1'
$env:MCP_PORT='8001'
$env:LOG_LEVEL='INFO'
.\.venv\Scripts\python.exe -m parachute.mcp_server
```

### Terminal 2 — A2A

```powershell
$env:PARACHUTE_MODE='demo'
$env:MCP_SERVER_URL='http://127.0.0.1:8001/mcp'
$env:MCP_TIMEOUT_SECONDS='10'
$env:A2A_HOST='127.0.0.1'
$env:A2A_PORT='8000'
$env:A2A_SERVER_URL='http://127.0.0.1:8000'
$env:LOG_LEVEL='INFO'
.\.venv\Scripts\python.exe -m parachute.a2a_server
```

Compruebe el descubrimiento desde otra consola:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/.well-known/agent-card.json' |
    ConvertTo-Json -Depth 20
```

### Terminal 3 — cliente

```powershell
$env:A2A_SERVER_URL='http://127.0.0.1:8000'
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.cli_a2a `
    --server-url 'http://127.0.0.1:8000' `
    --cliente 'Cliente Demo'
```

La ayuda completa está disponible con:

```powershell
.\.venv\Scripts\python.exe -m parachute.cli_a2a --help
```

Pruebe una FAQ del corpus, una pregunta sin evidencia y reservas usando las
fechas recién calculadas. Para el escenario `viento_marginal`, cierre la
terminal y vuelva a abrirla con `--tandem-experimentado`; la opción es un
booleano real y está desactivada por defecto.

## 11. Inspección y reinicio de la demo

Use exactamente la misma `DEMO_APPOINTMENTS_DB` con la que inició MCP:

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.demo_admin appointments
```

Detenga o deje de enviar solicitudes antes de reiniciar. El reinicio no borra
el archivo, exige `--confirm` y rechaza bases sin la marca interna de demo:

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.demo_admin reset --confirm
```

No hay limpieza automática al arrancar, por lo que una ejecución posterior
puede encontrar duplicados creados en una sesión anterior.

## 12. Modalidad real

El modo real requiere PostgreSQL con pgvector, el corpus cargado, el modelo de
embeddings disponible y acceso a Open-Meteo. Usa la SQLite indicada por
`APPOINTMENTS_DB`. NVIDIA no interviene en el recorrido MCP/A2A descrito aquí;
sí se usa en las evaluaciones Promptfoo y en componentes heredados que invoquen
ese cliente.

Terminal 1:

```powershell
$env:PARACHUTE_MODE='real'
$env:DATABASE_URL='postgresql://parachute:parachute@localhost:5432/parachute'
$env:EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:EMBEDDING_DIMENSION='384'
$env:APPOINTMENTS_DB='appointments.sqlite3'
$env:MCP_HOST='127.0.0.1'
$env:MCP_PORT='8001'
$env:LOG_LEVEL='INFO'
.\.venv\Scripts\python.exe -m parachute.mcp_server
```

Terminal 2:

```powershell
$env:PARACHUTE_MODE='real'
$env:MCP_SERVER_URL='http://127.0.0.1:8001/mcp'
$env:MCP_TIMEOUT_SECONDS='10'
$env:A2A_HOST='127.0.0.1'
$env:A2A_PORT='8000'
$env:A2A_SERVER_URL='http://127.0.0.1:8000'
$env:LOG_LEVEL='INFO'
.\.venv\Scripts\python.exe -m parachute.a2a_server
```

Terminal 3:

```powershell
$env:A2A_SERVER_URL='http://127.0.0.1:8000'
.\.venv\Scripts\python.exe -m parachute.cli_a2a `
    --server-url 'http://127.0.0.1:8000' `
    --cliente 'Ana'
```

Esta fase documental no realizó reservas reales ni llamadas a PostgreSQL,
Open-Meteo o NVIDIA. Por tanto, esos servicios deben verificarse en el entorno
de entrega antes de presentar el modo real.

## 13. Verificación y evidencia

Comandos de comprobación local:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short
```

La suite automatizada usa fixtures deterministas para FAQ y clima, servidores
MCP Streamable HTTP y A2A JSON-RPC reales sobre HTTP, y SQLite temporal. Incluye
descubrimiento, invocación de herramientas, recurso, prompt, Agent Card,
contratos, errores, aislamiento, cierre y el punto de entrada real de la
terminal. No sustituye una prueba de las dependencias externas del modo real.

Resultado real de la ejecución final de Fase 7, realizada con Python 3.13.3:

- **69/69 pruebas aprobadas** en 24.438 s (27.157 s de tiempo de pared);
- `pip check`: **No broken requirements found**;
- se verificaron los `--help` de la terminal A2A, el administrador demo y las
  tres interfaces locales;
- `demo_admin dates` produjo los cuatro escenarios relativos vigentes.

No se hicieron reservas reales ni solicitudes a PostgreSQL, Open-Meteo o
NVIDIA. La salida extensa de pruebas no se guarda como artefacto para evitar
versionar logs generados.

## 14. Solución de problemas y matriz de aceptación

- Si `python` no encuentra `mcp`, `a2a` o `dotenv`, use el intérprete de
  `.venv` mostrado en todos los comandos.
- Si la Agent Card no abre, confirme el log de A2A, puerto 8000 y la ruta
  `/.well-known/agent-card.json`.
- Si A2A informa que MCP no está disponible, confirme el log MCP, puerto 8001 y
  que `MCP_SERVER_URL` termina en `/mcp`.
- Si la terminal muestra `REAL` durante la demo, reinicie A2A con
  `PARACHUTE_MODE=demo`. Revise por separado que MCP también indique
  `MODO DEMO` en su log.
- Si una reserva resulta duplicada, inspeccione la SQLite demo o reiníciela de
  forma segura después de detener las solicitudes.
- Si se pierde una respuesta de reserva, no repita de inmediato: inspeccione la
  agenda porque la escritura pudo haberse completado.

| Requisito | Implementación | Evidencia | Estado | Limitación pendiente |
|---|---|---|---|---|
| Servidor MCP único | Cinco tools, recurso y prompt por Streamable HTTP | `test_hoja7_mcp.py` | Implementado; verificado con fixtures | Integración externa real pendiente |
| Cliente MCP y supervisor | Gateway remoto, contratos, correlación y cierre aislado | `test_hoja7_mcp_client.py` | Implementado; verificado con fixtures | Ningún respaldo local por diseño |
| Servidor A2A | Agent Card, dos skills y JSON-RPC oficial | `test_hoja7_a2a.py` | Implementado; verificado sobre HTTP | El modo anunciado no certifica MCP |
| Terminal A2A | Descubrimiento oficial, múltiples consultas y categorías | `test_hoja7_cli_a2a.py` | Implementado; verificado sobre HTTP | Sin memoria conversacional |
| Demo reproducible | Calendario relativo, corpus versionado y SQLite marcada | `test_hoja7_demo.py` | Implementado; verificado con fixtures | No representa disponibilidad de servicios externos |
| Reglas de seguridad | Servicios de dominio reutilizados y revalidación al crear | Suites Hoja 5 y Hoja 7 | Implementado; verificado | Ninguna regla delegada al LLM |
| Recorrido completo | Terminal → A2A → supervisor → MCP → respuesta | Prueba E2E automatizada de demo | Implementado; verificado con fixtures | No es una prueba externa real |
| Modo real | PostgreSQL/pgvector, embeddings y Open-Meteo | Código y configuración | Implementación completa | Verificación externa pendiente |
| Video | Guion cronometrado y comandos relativos | `docs/guion_video_hoja7.md` | Preparado | Grabación pendiente del usuario |
| Publicación/entrega | Documentación y artefactos locales | README y esta guía | Preparado | Publicación y entrega pendientes del usuario |

La implementación técnica está completa según las pruebas automatizadas. La
entrega académica completa no debe declararse final hasta que el usuario grabe
el video, valide el entorno real si se exige y publique los artefactos.
