import os


DEFAULT_DATABASE_URL = "postgresql://parachute:parachute@localhost:5432/parachute"
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_LLM_MODEL = "nvidia/nemotron-3-nano-30b-a3b"


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def embedding_model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def embedding_dimension() -> int:
    value = int(os.getenv("EMBEDDING_DIMENSION", DEFAULT_EMBEDDING_DIMENSION))
    if not 1 <= value <= 2_000:
        raise ValueError("EMBEDDING_DIMENSION debe estar entre 1 y 2000")
    return value
