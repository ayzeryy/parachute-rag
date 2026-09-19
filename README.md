# Agente RAG de Parachute S.A. — Hoja de trabajo 4

Agente de terminal que responde preguntas sobre el evento de Parachute S.A.
utilizando un flujo RAG real. Las 120 fichas del corpus se convierten en
embeddings locales, se almacenan en PostgreSQL con `pgvector` y se recuperan
mediante una herramienta (`function calling`) antes de que el LLM redacte cada
respuesta.

## Arquitectura

```text
Corpus_FAQs_Parachute_SA_2026.txt
              │
              ▼
        load_faqs.py ── paraphrase-multilingual-MiniLM-L12-v2
              │                         (384 dimensiones)
              ▼
      PostgreSQL + pgvector + índice HNSW
              ▲
              │ búsqueda por similitud coseno
      herramienta buscar_faqs
              ▲
              │
          app.py ───────── NVIDIA Build (LLM)
```

Los dos programas solicitados son:

- `load_faqs.py`: analiza el corpus, genera los embeddings y llena la tabla
  `faq_embeddings`.
- `app.py`: agente interactivo que configura `buscar_faqs` como herramienta del
  SDK de OpenAI compatible con NVIDIA Build.

## Requisitos

- Python 3.11 o posterior.
- Docker Desktop con el motor iniciado (también puede utilizarse Podman Compose).
- Una API key de [NVIDIA Build](https://build.nvidia.com/).
- Aproximadamente 500 MB libres para las dependencias y el modelo local.

## 1. Preparar el entorno

En PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

En Linux o macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edite `.env` y reemplace `nvapi-tu_clave_aqui` por su API key. El archivo
`.env` está ignorado por Git y no debe publicarse.

## 2. Inicializar PostgreSQL y pgvector

Inicie la infraestructura:

```powershell
docker compose up -d
docker compose ps
```

El servicio usa la imagen oficial `pgvector/pgvector:0.8.6-pg16`, crea la
extensión `vector`, la tabla `faq_embeddings`, un índice HNSW para distancia
coseno y un volumen persistente. Espere a que `docker compose ps` muestre el
estado `healthy`.

Para comprobar la extensión y la tabla:

```powershell
docker compose exec postgres psql -U parachute -d parachute -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
docker compose exec postgres psql -U parachute -d parachute -c "SELECT COUNT(*) FROM faq_embeddings;"
```

El segundo comando mostrará cero registros antes de ejecutar el cargador y 120
después de hacerlo.

## 3. Ejecutar el programa de carga

```powershell
python load_faqs.py
```

La primera ejecución descarga `paraphrase-multilingual-MiniLM-L12-v2`, un
modelo compacto de 384 dimensiones entrenado para más de 50 idiomas. Se eligió
la variante multilingüe porque el corpus y las consultas están en español. El
programa:

1. valida y transforma las 120 fichas del corpus;
2. genera embeddings normalizados de 384 dimensiones;
3. reemplaza el contenido previo de `faq_embeddings` dentro de una transacción;
4. actualiza el índice y las estadísticas de PostgreSQL.

También se puede elegir otro archivo o tamaño de lote:

```powershell
python load_faqs.py --file .\Corpus_FAQs_Parachute_SA_2026.txt --batch-size 16
```

## 4. Ejecutar el agente

```powershell
python app.py
```

Ejemplo:

```text
Agente RAG de Parachute S.A.
Escribe 'Bye' para salir o presiona Ctrl+C.

Tú: ¿Se realizan saltos nocturnos?
Agente: ... (FAQ-116)

Tú: ¿Quién ganó el mundial de fútbol?
Agente: No puedo responder esa pregunta con la información disponible.

Tú: Bye
Agente: ¡Hasta luego!
```

Para cada pregunta, el SDK obliga al modelo a llamar primero a
`buscar_faqs`. La herramienta genera el embedding de la consulta, ejecuta una
búsqueda por similitud coseno en pgvector y devuelve como máximo ocho fichas.
El modelo recibe únicamente esos resultados como evidencia. Se conservan las
últimas cuatro interacciones para permitir preguntas de seguimiento.

## Configuración

Las variables disponibles en `.env.example` son:

| Variable | Propósito | Valor predeterminado |
|---|---|---|
| `NVIDIA_API_KEY` | Credencial de NVIDIA Build | requerido |
| `NVIDIA_MODEL` | Modelo que ejecuta el agente | `nvidia/nemotron-3-nano-30b-a3b` |
| `DATABASE_URL` | Conexión de PostgreSQL | `postgresql://parachute:parachute@localhost:5432/parachute` |
| `EMBEDDING_MODEL` | Modelo local de embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `EMBEDDING_DIMENSION` | Dimensión de la columna vectorial | `384` |
| `MIN_SIMILARITY` | Umbral mínimo para recuperar una ficha | `0.35` |

Si se cambia el modelo por uno con otra dimensión, también se debe actualizar
`EMBEDDING_DIMENSION`, la declaración `VECTOR(...)` de `infra/init.sql` y
recrear el volumen con `docker compose down -v`.

## Pruebas

Las pruebas no consumen la API ni requieren PostgreSQL:

```powershell
python -m unittest discover -s tests -v
```

Cubren el análisis del corpus real, unicidad de sus 120 fichas, el esquema de la
herramienta, su ejecución antes de responder y el rechazo de respuestas cuando
el modelo no utiliza la herramienta.

## Detener o reiniciar la infraestructura

Detener conservando la información:

```powershell
docker compose down
```

Eliminar también el volumen y comenzar desde cero:

```powershell
docker compose down -v
docker compose up -d
python load_faqs.py
```

El último procedimiento elimina la base local del proyecto; el corpus original
permanece intacto.

## Video de entrega

El video puede ser corto y sin narración. Debe mostrar, en este orden:

1. `docker compose ps` con PostgreSQL en estado `healthy`;
2. `python load_faqs.py` terminando con 120 fichas cargadas;
3. la consulta SQL `SELECT COUNT(*) FROM faq_embeddings;`;
4. `python app.py` respondiendo una pregunta incluida en el corpus;
5. una pregunta ajena al corpus y la respuesta de rechazo;
6. la salida con `Bye`.

## Referencias

- [pgvector](https://github.com/pgvector/pgvector)
- [pgvector para Python](https://github.com/pgvector/pgvector-python)
- [Sentence Transformers](https://www.sbert.net/)
