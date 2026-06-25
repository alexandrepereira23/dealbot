import os
from dotenv import load_dotenv

load_dotenv()


def _req(chave: str) -> str:
    valor = os.environ.get(chave)
    if not valor:
        raise RuntimeError(f"Variável de ambiente ausente: {chave}")
    return valor


class Config:
    TG_API_ID = int(_req("TG_API_ID"))
    TG_API_HASH = _req("TG_API_HASH")
    TG_SESSION_STRING = _req("TG_SESSION_STRING")
    SUPABASE_URL = _req("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = _req("SUPABASE_SERVICE_KEY")
    GEMINI_API_KEY = _req("GEMINI_API_KEY")
