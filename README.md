# Agente RAG de Parachute S.A.

Hoja de trabajo 3 de CC3116. El programa responde preguntas sobre el evento de
Parachute S.A. usando la información del archivo de preguntas frecuentes.

El archivo se carga desde el sistema, se agrega al mensaje de contexto y luego
se envía la pregunta al modelo de NVIDIA. Cuando el documento no contiene la
respuesta, el agente lo indica.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copia `.env.example` como `.env` y coloca una API key de
[NVIDIA Build](https://build.nvidia.com/) en `NVIDIA_API_KEY`.

## Ejecución

```powershell
.\.venv\Scripts\python.exe app.py
```

Se pueden hacer varias preguntas en la misma sesión. Para salir, escribe `Bye`
o presiona `Ctrl+C`.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

El archivo `.env` está ignorado por Git para evitar publicar la API key.
