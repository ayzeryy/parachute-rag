# Parachute S.A. - Hojas de trabajo 5, 6 y 7

Sistema multiagente que conserva el RAG de FAQs de la hoja 4 y agrega reservas
condicionadas por el pronóstico de Open-Meteo. El mismo problema se implementa
en tres programas con orquestación centralizada, jerárquica y descentralizada.

## Hoja de trabajo 7: interoperabilidad MCP y A2A

La Hoja 7 expone la composición centralizada como un agente A2A y separa las
herramientas de dominio en un único servidor MCP con Streamable HTTP:

```text
Terminal A2A → servidor A2A → supervisor central asíncrono
             → cliente MCP → servidor MCP → servicios de dominio
```

El servidor MCP publica cinco herramientas (`buscar_faqs`, `extraer_fecha`,
`consultar_clima`, `evaluar_seguridad` y `crear_cita`), el recurso
`parachute://politicas/seguridad` y el prompt `consulta_faq`. El agente externo
se llama **Asistente Parachute S.A.** y anuncia las skills `consultar_faqs` y
`reservar_salto`.

- [Guía técnica, contratos, ejecución y matriz de aceptación](docs/hoja7.md)
- [Guion de video de 4–7 minutos](docs/guion_video_hoja7.md)
- [Video final y manifiesto de evidencias](docs/evidencias/hoja7/README.md)
- [Diagramas de las arquitecturas anteriores](docs/diagramas.md)

### Demostración rápida

Instala primero las dependencias y consulta las fechas relativas de la demo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.demo_admin dates
```

Después inicia MCP, A2A y la terminal en tres consolas. Los comandos completos,
incluidas las variables que deben declararse en **cada** proceso, están en la
[guía técnica](docs/hoja7.md#demostración-local-en-tres-terminales). El modo
demo usa datos externos deterministas y una SQLite separada, pero ejecuta
realmente la terminal, A2A, MCP, el supervisor y las reglas de seguridad.

### Modalidades y versiones verificadas

| Aspecto | `demo` | `real` |
|---|---|---|
| FAQs | Búsqueda léxica sobre el corpus versionado | PostgreSQL, pgvector y embeddings locales |
| Clima | Escenarios relativos deterministas | Open-Meteo |
| Citas | `.demo/appointments.demo.sqlite3`, marcada como demo | `APPOINTMENTS_DB` |
| Protocolos y dominio | A2A, MCP, supervisor y reglas reales | Los mismos componentes |

El requisito declarado sigue siendo Python 3.11 o posterior. La combinación
efectivamente probada en este repositorio es Python **3.13.3**, `mcp==2.3.0` y
`a2a-sdk[http-server]==1.2.2`. La integración real con PostgreSQL y Open-Meteo
requiere servicios externos y no se volvió a ejecutar durante el cierre
documental de la Hoja 7.

La Agent Card informa el modo configurado en el proceso A2A. No existe un
handshake que certifique el modo del servidor MCP: el operador debe configurar
ambos procesos de forma coherente y comprobar sus logs de arranque.

### Verificación

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

La suite usa fixtures deterministas, servidores HTTP reales y SQLite temporal;
no consume PostgreSQL, Open-Meteo ni NVIDIA. Los resultados concretos de la
última ejecución se registran en la [guía de la Hoja 7](docs/hoja7.md#verificación-y-evidencia).

## Entregables

| Programa | Arquitectura | Orquestador |
|---|---|---|
| `centralizada.py` | Centralizada | `CentralSupervisor` coordina directamente a todos los especialistas. |
| `jerarquica.py` | Jerárquica | `ExecutiveManager` delega a managers de información y operaciones. |
| `descentralizada.py` | Descentralizada | `PeerNetwork` transfiere el contexto mediante handoffs entre pares. |

Los diagramas Mermaid están en [`docs/diagramas.md`](docs/diagramas.md) y el
informe con las respuestas está en `informe_hoja5.pdf`.

## Hoja de trabajo 6: evals con Promptfoo

Para cerrar el ciclo se evaluó la arquitectura **centralizada**. Es la opción
más adecuada para este despliegue porque el `CentralSupervisor` controla de
forma explícita el orden de todos los especialistas y mantiene las decisiones
críticas de seguridad fuera del LLM.

La configuración está en [`promptfooconfig.yaml`](promptfooconfig.yaml) y usa
[`evals/provider.py`](evals/provider.py) como proveedor Python. El proveedor
ejecuta el supervisor real y reemplaza solo los límites no deterministas por
fixtures: Open-Meteo, pgvector y SQLite. Esto evita cambios persistentes y hace
que los casos puedan repetirse.

La suite contiene cinco escenarios, dos de FAQ y tres de citas. En ambas
funcionalidades se califican:

- `factuality` con un juez LLM y una respuesta de referencia;
- métricas determinísticas `contains` y `regex`;
- `latency` con un máximo de 1,000 ms y caché desactivada;
- `tool-call-f1` para exigir exactamente la ruta de herramientas esperada.

El último resultado fue **5/5 casos y 25/25 aserciones aprobadas**. Los
artefactos generados directamente por Promptfoo están en:

- [`output/promptfoo-report.html`](output/promptfoo-report.html), reporte para
  entregar o abrir en el navegador;
- [`output/promptfoo-results.json`](output/promptfoo-results.json), resultados
  completos y auditables.

Para repetir la evaluación se necesita Node.js 20 o posterior y
`NVIDIA_API_KEY` en `.env`:

```powershell
npm install
npm run eval
```

El script usa `--no-cache`, requisito de Promptfoo para medir latencia. La clave
solo se lee desde el ambiente y nunca se incluye en el reporte o repositorio.

## Diseño compartido

La carpeta `parachute/` evita duplicar lógica entre arquitecturas:

- `weather.py`: consulta Open-Meteo para las coordenadas 14.013722,
  -90.771611 y valida la ventana inclusiva de 16 días.
- `safety.py`: aplica los umbrales de viento, ráfagas, precipitación y nubes.
- `calendar.py`: persiste únicamente citas permitidas en SQLite.
- `agents.py`: especialistas de triaje, fecha, clima, seguridad, agenda y FAQ.
- `factory.py`: construye los mismos agentes e integraciones para los tres
  programas.
- `centralized.py`, `hierarchical.py`, `decentralized.py`: contienen solamente
  la estrategia de coordinación.

Las reglas críticas son deterministas y se prueban sin depender de un LLM. Esto
impide que una respuesta creativa pueda saltarse un criterio de seguridad. El
agente FAQ conserva PostgreSQL, pgvector y embeddings locales de la hoja 4.

## Preparación

Requiere Python 3.11 o posterior, Docker y las dependencias de
`requirements.txt`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
docker compose up -d
python load_faqs.py
```

La API de Open-Meteo no requiere clave. `.env` solo es necesario para el RAG
heredado y su cliente de NVIDIA Build.

## Ejecutar los tres programas

```powershell
python centralizada.py --cliente "Ana"
python jerarquica.py --cliente "Ana"
python descentralizada.py --cliente "Ana"
```

## Demostración A2A reproducible

El modo normal sigue siendo `PARACHUTE_MODE=real`. Para una demostración local
sin PostgreSQL, Open-Meteo, NVIDIA ni descarga de embeddings, configura en
`.env`:

```dotenv
PARACHUTE_MODE=demo
DEMO_APPOINTMENTS_DB=.demo/appointments.demo.sqlite3
```

Consulta primero las cuatro fechas relativas disponibles en
`America/Guatemala`; el calendario se recalcula cada día y no requiere reiniciar
los servidores para cambiar de escenario:

```powershell
python -m parachute.demo_admin dates
```

Luego ejecuta, en tres terminales distintas:

```powershell
python -m parachute.mcp_server
python -m parachute.a2a_server
python -m parachute.cli_a2a --cliente "Cliente Demo"
```

La terminal muestra el modo que el proceso A2A anuncia en la Agent Card; revise
por separado el log MCP para confirmar que también inició en `MODO DEMO`.
Las fechas `ideal`, `prohibido`, `viento_marginal` y `nubes_marginales`
seleccionan pronósticos deterministas; el usuario nunca envía valores
meteorológicos. Para inspeccionar o reiniciar exclusivamente la SQLite marcada
como demo:

```powershell
python -m parachute.demo_admin appointments
python -m parachute.demo_admin reset --confirm
```

El reinicio no se ejecuta al arrancar, exige confirmación y rechaza una ruta que
coincida con `APPOINTMENTS_DB` o que no tenga la marca interna de demo.

Para la modalidad real, usa una fecha ISO dentro de la ventana vigente de
Open-Meteo. Por ejemplo, calcula una fecha relativa antes de escribir la
consulta:

```powershell
(Get-Date).AddDays(2).ToString('yyyy-MM-dd')
```

Si el viento en superficie está entre 20 y 28 km/h, la reserva solo se permite
al declarar un tándem experimentado:

```powershell
python centralizada.py --cliente "Ana" --tandem-experimentado
```

Las citas aceptadas se guardan por defecto en `appointments.sqlite3`. Se puede
cambiar con `APPOINTMENTS_DB`. El sistema nunca reserva si hay lluvia, viento
mayor a 28 km/h, ráfagas mayores a 35 km/h o nubes mayores a 75%.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

La suite actual no consume APIs externas. Además de las pruebas originales del
corpus, RAG, límites meteorológicos y tres arquitecturas, cubre los contratos y
recorridos HTTP de la Hoja 7. La última ejecución completa aprobó 69/69 pruebas;
consulte el detalle y sus límites en la guía técnica.

## Decisión sobre el SDK

La recomendación de `as_tool()` y `handoff` aplica cuando se usa OpenAI Agents
SDK. En esta solución los componentes de seguridad son agentes de software
deterministas y los handoffs son explícitos en `PeerNetwork`; no se requiere que
un LLM seleccione herramientas. Esta decisión mantiene compatibilidad con el
cliente NVIDIA/OpenAI ya usado por el proyecto y hace reproducibles las reglas
de negocio. Las clases de integración quedan desacopladas y pueden envolverse
posteriormente como tools sin modificar clima, seguridad ni persistencia.

## Referencias

- [Open-Meteo Forecast API](https://open-meteo.com/en/docs)
- [OpenAI Agents - managers as tools](https://openai.github.io/openai-agents-python/agents/#manager-agents-as-tools)
- [OpenAI Agents - handoffs](https://openai.github.io/openai-agents-python/agents/#handoffs)
- [pgvector](https://github.com/pgvector/pgvector)
