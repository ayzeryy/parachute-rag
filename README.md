# Parachute S.A. - Hojas de trabajo 5 y 6

Sistema multiagente que conserva el RAG de FAQs de la hoja 4 y agrega reservas
condicionadas por el pronóstico de Open-Meteo. El mismo problema se implementa
en tres programas con orquestación centralizada, jerárquica y descentralizada.

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
Copy-Item .env.example .env
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

Ejemplo: `Quiero reservar una cita el 2026-09-25`.

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

Las 15 pruebas no consumen APIs externas. Verifican el corpus, la herramienta
RAG, todos los límites meteorológicos, la ventana de Open-Meteo y la equivalencia
funcional de las tres arquitecturas.

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
