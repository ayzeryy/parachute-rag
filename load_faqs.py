import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from config import database_url, embedding_dimension, embedding_model_name


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS = BASE_DIR / "Corpus_FAQs_Parachute_SA_2026.txt"


@dataclass(frozen=True)
class FAQRecord:
    source_id: str
    category: str
    question: str
    answer: str
    metadata: dict

    @property
    def embedding_text(self) -> str:
        # The supplied answers contain repeated boilerplate, so embedding only the
        # question gives substantially cleaner semantic neighbors.
        return self.question


ENTRY_PATTERN = re.compile(
    r"^ID:\s*(?P<id>[^\r\n]+)\s*\r?\n"
    r"CATEGORÍA:\s*(?P<category>[^\r\n]+)\s*\r?\n"
    r"PREGUNTA:\s*(?P<question>.*?)\r?\n"
    r"RESPUESTA:\s*(?P<answer>.*?)\r?\n"
    r"METADATA:\s*(?P<metadata>\{[^\r\n]+\})\s*$",
    re.MULTILINE | re.DOTALL,
)


def parse_corpus(path: Path) -> list[FAQRecord]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"No se encontró el corpus: {path}") from exc

    records: list[FAQRecord] = []
    for block in re.split(r"^\s*-{20,}\s*$", content, flags=re.MULTILINE):
        match = ENTRY_PATTERN.search(block.strip())
        if not match:
            continue
        try:
            metadata = json.loads(match.group("metadata"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Metadata inválida en {match.group('id').strip()}"
            ) from exc
        records.append(
            FAQRecord(
                source_id=match.group("id").strip(),
                category=match.group("category").strip(),
                question=" ".join(match.group("question").split()),
                answer=" ".join(match.group("answer").split()),
                metadata=metadata,
            )
        )

    if not records:
        raise RuntimeError(f"No se encontraron fichas válidas en {path}")
    ids = [record.source_id for record in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("El corpus contiene identificadores duplicados")
    return records


def load_records(records: list[FAQRecord], batch_size: int = 32) -> int:
    import psycopg
    from pgvector import Vector
    from pgvector.psycopg import register_vector
    from sentence_transformers import SentenceTransformer

    dimension = embedding_dimension()
    model = SentenceTransformer(embedding_model_name())
    dimension_getter = getattr(model, "get_embedding_dimension", None)
    actual_dimension = (
        dimension_getter()
        if dimension_getter
        else model.get_sentence_embedding_dimension()
    )
    if actual_dimension != dimension:
        raise RuntimeError(
            f"El modelo produce {actual_dimension} dimensiones, pero la tabla usa "
            f"{dimension}. Ajusta EMBEDDING_DIMENSION antes de cargar."
        )

    texts = [record.embedding_text for record in records]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    with psycopg.connect(database_url()) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(connection)
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS faq_embeddings (
                id BIGSERIAL PRIMARY KEY,
                source_id TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                embedding VECTOR({dimension}) NOT NULL,
                loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        connection.execute("TRUNCATE TABLE faq_embeddings RESTART IDENTITY")
        rows = [
            (
                record.source_id,
                record.category,
                record.question,
                record.answer,
                json.dumps(record.metadata, ensure_ascii=False),
                Vector(embedding),
            )
            for record, embedding in zip(records, embeddings, strict=True)
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO faq_embeddings
                    (source_id, category, question, answer, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                """,
                rows,
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS faq_embeddings_embedding_hnsw_idx
            ON faq_embeddings USING hnsw (embedding vector_cosine_ops)
            """
        )
        connection.execute("ANALYZE faq_embeddings")
    return len(records)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Carga el corpus de FAQs y sus embeddings en PostgreSQL/pgvector."
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size debe ser mayor que cero")

    records = parse_corpus(args.file)
    print(f"Se encontraron {len(records)} fichas. Generando embeddings...")
    loaded = load_records(records, batch_size=args.batch_size)
    print(f"Carga completa: {loaded} fichas almacenadas en pgvector.")


if __name__ == "__main__":
    main()
