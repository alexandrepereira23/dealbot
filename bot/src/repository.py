import os
from datetime import datetime, timedelta, timezone

from .db import supabase
from .dedup import gerar_hash

BUCKET = "produtos"

# Janela usada para considerar que duas mensagens em canais diferentes
# falam da mesma promoção. Promoções relâmpago raramente passam de 48h.
JANELA_DEDUP_HORAS = 48


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


def buscar_duplicata(hash_oferta: str) -> int | None:
    """Procura promo com mesmo hash dentro da janela. Retorna produto_id ou None."""
    desde = (datetime.now(timezone.utc) - timedelta(hours=JANELA_DEDUP_HORAS)).isoformat()
    res = (
        supabase.table("produtos")
        .select("id")
        .eq("dedup_hash", hash_oferta)
        .gte("criado_em", desde)
        .order("criado_em", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["id"]
    return None


def registrar_aparicao(produto_id: int, canal: str, telegram_msg_id) -> None:
    """Insere aparição (idempotente pelo índice único canal+msg)."""
    try:
        supabase.table("produto_aparicoes").upsert(
            {
                "produto_id": produto_id,
                "canal_origem": canal,
                "telegram_msg_id": telegram_msg_id,
            },
            on_conflict="canal_origem,telegram_msg_id",
        ).execute()
    except Exception as e:
        print(f"[db] erro ao registrar aparição: {e}")


def salvar_produto(registro: dict) -> tuple[str, int | None]:
    """Salva uma promo deduplicando entre canais.

    Retorna (status, produto_id):
      - ("novo", id)       — primeira vez que vemos essa promo na janela.
      - ("duplicado", id)  — já existia em outro canal; só registra aparição.
      - ("erro", None)     — falhou.
    """
    canal = registro.get("canal_origem")
    msg_id = registro.get("telegram_msg_id")

    hash_oferta = gerar_hash(registro)
    registro_final = {**registro, "dedup_hash": hash_oferta}

    try:
        existente = buscar_duplicata(hash_oferta)
        if existente:
            registrar_aparicao(existente, canal, msg_id)
            return ("duplicado", existente)

        res = (
            supabase.table("produtos")
            .upsert(registro_final, on_conflict="canal_origem,telegram_msg_id")
            .execute()
        )
        produto_id = res.data[0]["id"] if res.data else None
        if produto_id:
            registrar_aparicao(produto_id, canal, msg_id)
        return ("novo", produto_id)
    except Exception as e:
        print(f"[db] erro ao salvar: {e}")
        return ("erro", None)


def listar_canais() -> list[str]:
    res = supabase.table("canais").select("username").eq("ativo", True).execute()
    return [c["username"] for c in (res.data or [])]
