import os


DEFAULT_DATABASE_URL = "postgresql://parachute:parachute@localhost:5432/parachute"
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_LLM_MODEL = "meta/llama-3.2-90b-vision-instruct"
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8001
DEFAULT_MCP_TIMEOUT_SECONDS = 10.0
DEFAULT_A2A_HOST = "127.0.0.1"
DEFAULT_A2A_PORT = 8000
DEFAULT_LOG_LEVEL = "INFO"


def _port_from_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= 65_535:
        raise ValueError(f"{name} debe estar entre 1 y 65535")
    return value


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def embedding_model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def embedding_dimension() -> int:
    value = int(os.getenv("EMBEDDING_DIMENSION", DEFAULT_EMBEDDING_DIMENSION))
    if not 1 <= value <= 2_000:
        raise ValueError("EMBEDDING_DIMENSION debe estar entre 1 y 2000")
    return value


def mcp_host() -> str:
    return os.getenv("MCP_HOST", DEFAULT_MCP_HOST)


def mcp_port() -> int:
    return _port_from_env("MCP_PORT", DEFAULT_MCP_PORT)


def mcp_server_url() -> str:
    return os.getenv(
        "MCP_SERVER_URL",
        f"http://{mcp_host()}:{mcp_port()}/mcp",
    ).rstrip("/")


def mcp_timeout_seconds() -> float:
    value = float(
        os.getenv("MCP_TIMEOUT_SECONDS", str(DEFAULT_MCP_TIMEOUT_SECONDS))
    )
    if value <= 0:
        raise ValueError("MCP_TIMEOUT_SECONDS debe ser mayor que cero")
    return value


def a2a_host() -> str:
    return os.getenv("A2A_HOST", DEFAULT_A2A_HOST)


def a2a_port() -> int:
    return _port_from_env("A2A_PORT", DEFAULT_A2A_PORT)


def a2a_server_url() -> str:
    return os.getenv(
        "A2A_SERVER_URL",
        f"http://{a2a_host()}:{a2a_port()}",
    ).rstrip("/")


def log_level() -> str:
    value = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if value not in allowed:
        raise ValueError(f"LOG_LEVEL debe ser uno de: {', '.join(sorted(allowed))}")
    return value
