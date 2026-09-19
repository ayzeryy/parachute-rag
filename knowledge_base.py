import os
from typing import Any

from config import database_url, embedding_dimension, embedding_model_name


class KnowledgeBase:
    def __init__(
        self,
        db_url: str,
        model_name: str,
        dimension: int,
        min_similarity: float = 0.35,
    ) -> None:
        self.db_url = db_url
        self.model_name = model_name
        self.dimension = dimension
        self.min_similarity = min_similarity
        self._model: Any = None

    @classmethod
    def from_env(cls) -> "KnowledgeBase":
        return cls(
            db_url=database_url(),
            model_name=embedding_model_name(),
            dimension=embedding_dimension(),
            min_similarity=float(os.getenv("MIN_SIMILARITY", "0.35")),
        )

    def _embedding_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            dimension_getter = getattr(self._model, "get_embedding_dimension", None)
            actual_dimension = (
                dimension_getter()
                if dimension_getter
                else self._model.get_sentence_embedding_dimension()
            )
            if actual_dimension != self.dimension:
                raise RuntimeError(
                    f"El modelo produce {actual_dimension} dimensiones, pero "
                    f"EMBEDDING_DIMENSION={self.dimension}."
                )
        return self._model

    def embed(self, text: str):
        return self._embedding_model().encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        import psycopg
        from pgvector import Vector
        from pgvector.psycopg import register_vector
        from psycopg.rows import dict_row

        query = query.strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 8))
        vector = Vector(self.embed(query))

        sql = """
            SELECT source_id, category, question, answer, metadata,
                   1 - (embedding <=> %s) AS similarity
            FROM faq_embeddings
            WHERE 1 - (embedding <=> %s) >= %s
            ORDER BY embedding <=> %s
            LIMIT %s
        """
        with psycopg.connect(self.db_url, row_factory=dict_row) as connection:
            register_vector(connection)
            rows = connection.execute(
                sql,
                (vector, vector, self.min_similarity, vector, limit),
            ).fetchall()

        return [
            {
                "id": row["source_id"],
                "categoria": row["category"],
                "pregunta": row["question"],
                "respuesta": row["answer"],
                "metadata": row["metadata"],
                "similitud": round(float(row["similarity"]), 4),
            }
            for row in rows
        ]
