# Guion de video — Hoja de trabajo 7

Duración objetivo: **6 minutos**. Ejecute todo desde la raíz del repositorio.
Antes de grabar, instale dependencias, reinicie únicamente la base demo marcada
y abra tres terminales. No muestre `.env`, claves ni información personal.

La frase que debe decirse literalmente durante la introducción es:

> Esta demostración utiliza datos externos deterministas; la terminal, A2A, MCP, el sistema multiagente y las reglas de seguridad se ejecutan realmente

## Preparación fuera de cámara

Consulte el calendario relativo y copie las cuatro fechas que devuelve. No use
fechas permanentes en diapositivas ni en el video:

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
$env:DEMO_CORPUS_PATH='Corpus_FAQs_Parachute_SA_2026.txt'
.\.venv\Scripts\python.exe -m parachute.demo_admin dates
```

Detenga las solicitudes antes de limpiar una ejecución anterior:

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.demo_admin reset --confirm
```

Inicie MCP y A2A con los bloques exactos de
[`docs/hoja7.md`](hoja7.md#demostración-local-en-tres-terminales). Mantenga
visibles sus logs. No reinicie servidores entre escenarios.

## 0:00–0:40 — objetivo y arquitectura

**Mostrar:** el diagrama Mermaid de `docs/hoja7.md` o los archivos
`cli_a2a.py`, `a2a_server.py`, `mcp_centralized.py`, `mcp_client.py` y
`mcp_server.py`.

**Explicar:** existe un agente externo, `Asistente Parachute S.A.`, con dos
skills. La terminal habla A2A con el servidor, el supervisor hace triaje local
y las demás operaciones cruzan MCP por HTTP. Las reglas deterministas siguen en
el dominio. Decir la frase obligatoria completa indicada al inicio.

**Evidencia:** arquitectura y separación entre protocolos, coordinación y
dominio.

## 0:40–1:15 — calendario y servidores

**Mostrar:** la salida ya obtenida de `demo_admin dates`, los logs de arranque de
MCP y A2A y las etiquetas `MODO DEMO`.

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.demo_admin dates
```

**Explicar:** las fechas se calculan en `America/Guatemala`; elegir una fecha
selecciona un escenario determinista, pero el usuario no suministra el clima.
La SQLite demo está separada y marcada. La Agent Card anuncia el modo de A2A,
pero no certifica el modo MCP; ambos logs deben revisarse.

**Evidencia:** cuatro escenarios vigentes sin fechas que caduquen.

## 1:15–1:50 — descubrimiento A2A

**Mostrar:** la Agent Card y luego la conexión de la terminal.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/.well-known/agent-card.json' |
    ConvertTo-Json -Depth 20
```

```powershell
$env:A2A_SERVER_URL='http://127.0.0.1:8000'
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.cli_a2a `
    --server-url 'http://127.0.0.1:8000' `
    --cliente 'Cliente Demo'
```

**Explicar:** el cliente oficial descubre nombre, interfaz y skills; cada
consulta genera IDs nuevos y es independiente.

**Evidencia:** nombre del agente, `consultar_faqs`, `reservar_salto` y modo.

## 1:50–2:35 — FAQ con y sin evidencia

**Escribir en la terminal:**

```text
¿Cuál es el peso máximo permitido para saltar?
```

**Salida esperada, no pregrabada:** respuesta del corpus con la cita
`(FAQ-021)`. Verifique en vivo el texto devuelto; no memorice ni modifique la
respuesta.

Luego escriba:

```text
¿Qué color tiene el submarino de la empresa?
```

**Salida esperada, no pregrabada:** `No puedo responder esa pregunta con la
información disponible.`

**Explicar:** MCP ejecuta `buscar_faqs`; con evidencia responde y cita la ficha,
sin evidencia no inventa. Señalar la misma correlación en terminal, A2A y MCP.

## 2:35–3:20 — reserva ideal

**Escribir:** reemplace `<FECHA_IDEAL>` por la fecha `ideal` mostrada por
`demo_admin dates`.

```text
Quiero reservar un salto el <FECHA_IDEAL>.
```

**Salida esperada, no pregrabada:** categoría de reserva procesada y mensaje de
cita creada.

**Explicar:** el supervisor recorrió fecha, clima y seguridad por MCP;
`crear_cita` volvió a consultar y evaluar antes de persistir. La decisión final
de `crear_cita` es la autoridad.

**Evidencia:** logs MCP de `extraer_fecha`, `consultar_clima`,
`evaluar_seguridad` y `crear_cita`, con duración y una correlación común.

## 3:20–3:55 — rechazo meteorológico

**Escribir:** reemplace `<FECHA_PROHIBIDA>` por `prohibido`.

```text
Quiero reservar un salto el <FECHA_PROHIBIDA>.
```

**Salida esperada, no pregrabada:** reserva rechazada por precipitación.

**Explicar:** es un resultado normal de negocio, no una caída técnica, y no se
escribe una cita.

**Evidencia:** categoría legible en terminal y resultado `rejected` en MCP.

## 3:55–4:50 — viento marginal y booleano de experiencia

Con la terminal actual, escriba una reserva usando `<FECHA_VIENTO_MARGINAL>`.

```text
Quiero reservar un salto el <FECHA_VIENTO_MARGINAL>.
```

**Salida esperada, no pregrabada:** rechazo porque la experiencia está
desactivada por defecto.

Salga con `salir` y abra otra terminal declarando el booleano mediante el flag:

```powershell
$env:A2A_SERVER_URL='http://127.0.0.1:8000'
.\.venv\Scripts\python.exe -m parachute.cli_a2a `
    --server-url 'http://127.0.0.1:8000' `
    --cliente 'Cliente Experimentado' `
    --tandem-experimentado
```

Repita la solicitud con la misma fecha marginal.

**Salida esperada, no pregrabada:** cita creada para el cliente distinto.

**Explicar:** no se infiere experiencia del texto y nunca se transmite la
cadena `"false"`; el flag produce un booleano real.

## 4:50–5:25 — persistencia e inspección segura

**Mostrar:** en otra consola, con la misma ruta de base:

```powershell
$env:DEMO_APPOINTMENTS_DB='.demo/appointments.demo.sqlite3'
.\.venv\Scripts\python.exe -m parachute.demo_admin appointments
```

**Explicar:** deben aparecer las reservas aprobadas, no la prohibida ni el
primer intento marginal. El reinicio requiere detener solicitudes, usar la
misma ruta y añadir `--confirm`; no se ejecuta automáticamente.

**Evidencia:** filas persistidas con fecha y condición, sin abrir SQLite a mano.

## 5:25–6:00 — pruebas, límites y cierre

**Mostrar:** la sección de verificación de `docs/hoja7.md` y, si cabe, la última
salida real de la suite.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

**Explicar:** las pruebas usan servidores HTTP reales y fixtures deterministas;
no prueban PostgreSQL, Open-Meteo o NVIDIA. La integración externa real queda
pendiente de validación en el entorno de entrega. Una respuesta perdida de
`crear_cita` se clasifica como resultado incierto y no se reenvía.

**Evidencia:** suite aprobada, guía técnica y matriz de aceptación. Cierre las
terminales con `salir` y Ctrl+C. No afirme que el video está publicado hasta
haberlo subido y comprobado.

## Lista de control de grabación

- La Agent Card muestra exactamente dos skills.
- MCP y A2A muestran `MODO DEMO` en sus propios logs.
- Las fechas provienen de `demo_admin dates` el día de la grabación.
- La FAQ con evidencia cita `FAQ-021`; la desconocida no inventa.
- Se ve una reserva creada, una rechazada y el caso marginal con/sin flag.
- Se muestra la correlación a través de terminal, A2A y MCP.
- `appointments` contiene solo escrituras aprobadas.
- No aparecen claves, `.env`, nombres reales ni datos sensibles.
- Se aclaran fixtures, limitaciones externas y publicación pendiente.
