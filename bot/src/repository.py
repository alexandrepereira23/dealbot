import os
from .db import supabase

BUCKET = "produtos"


async def subir_foto(msg) -> str | None:
    """Baixa a mídia da mensagem e sobe para o Storage. Retorna URL pública."""
    if not getattr(msg, "photo", None):
        return None
    try:
        caminho = await msg.download_media(file="/tmp/")
        nome = f"{msg.chat_id}_{msg.id}.jpg"
        with open(caminho, "rb") as fp:
            supabase.storage.from_(BUCKET).upload(
                nome, fp, {"content-type": "image/jpeg", "upsert": "true"}
            )
        os.remove(caminho)
        return supabase.storage.from_(BUCKET).get_public_url(nome)
    except Exception as e:
        print(f"[storage] erro: {e}")
        return None


def salvar_produto(registro: dict) -> bool:
    try:
        supabase.table("produtos").upsert(
            registro, on_conflict="canal_origem,telegram_msg_id"
        ).execute()
        return True
    except Exception as e:
        print(f"[db] erro ao salvar: {e}")
        return False


def listar_canais() -> list[str]:
    res = supabase.table("canais").select("username").eq("ativo", True).execute()
    return [c["username"] for c in (res.data or [])]
