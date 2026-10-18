# Evidencia audiovisual — Hoja de trabajo 7

Esta carpeta conserva la demostración final de la Hoja 7 y los recursos mínimos
para verificarla o volver a publicarla. El video no tiene voz, música ni audio;
los rótulos y subtítulos en español permiten seguir toda la ejecución.

## Archivos

- [`hoja7_demostracion_1080p.mp4`](hoja7_demostracion_1080p.mp4): video final.
- [`hoja7_demostracion_es.srt`](hoja7_demostracion_es.srt): subtítulos externos
  editables. El MP4 también contiene una pista de subtítulos.
- [`SHA256SUMS.txt`](SHA256SUMS.txt): suma de integridad del MP4.
- [`../../guion_video_hoja7.md`](../../guion_video_hoja7.md): guion y comandos de
  reproducción de la demostración.

## Qué demuestra

La grabación muestra capturas de ejecuciones reales del modo demo:

- MCP mediante Streamable HTTP, sus herramientas y sus logs;
- A2A mediante JSON-RPC, la Agent Card y las skills `consultar_faqs` y
  `reservar_salto`;
- el cliente oficial de terminal y las respuestas recibidas;
- FAQ con evidencia `FAQ-021` y FAQ sin evidencia;
- reserva aprobada, rechazo por precipitación y el caso marginal de viento sin
  experiencia y con experiencia;
- una correlación visible entre terminal, A2A y MCP;
- persistencia exclusiva de las dos reservas aprobadas en SQLite demo;
- una ejecución capturada de la suite: 69 pruebas aprobadas en 29.439 s, seguida
  de `pip check` sin conflictos.

## Metadatos verificados

| Propiedad | Valor |
|---|---|
| Resolución | 1920 × 1080 |
| Duración | 00:05:36.50 |
| Video | H.264 High, `yuv420p`, 20 fps |
| Audio | Sin pista de audio |
| Subtítulos | Español, pista `mov_text` integrada y copia SRT |
| Tamaño | 13,939,829 bytes |
| SHA-256 | `DE63E7215091DA51EC25584CECA80EBD7314F61F30A8066F0EAA9A96BE9222CD` |

La decodificación completa del MP4 se verificó localmente antes de incorporarlo
al repositorio.

## Alcance y privacidad

La demostración usa fechas relativas obtenidas con `demo_admin dates`, clientes
ficticios, dependencias externas deterministas y una base SQLite exclusiva de
demo. No crea reservas reales ni prueba PostgreSQL, Open-Meteo o NVIDIA
externos. Las notificaciones del escritorio fueron ocultadas y no se muestran
credenciales. La publicación o entrega externa del artefacto queda a cargo del
usuario.
