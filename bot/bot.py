"""
DEALBOT - Bot de monitoramento de promoções
Telethon + Gemini + Supabase

Funciona em DOIS modos (escolha pela variável MODO):
  - "live"    -> conexão persistente (rode num VPS, ex: Oracle Cloud)
  - "polling" -> roda uma vez e sai (compatível com cron/GitHub Actions)
"""

import os
import re
import json
import asyncio
import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import google.generativeai as genai
from supabase import create_client, Client

# ============================================================
# CONFIG (tudo via variáveis de ambiente / secrets)
# ============================================================
API_ID      = int(os.environ["TG_API_ID"])
API_HASH    = os.environ["TG_API_HASH"]
SESSION_STR = os.environ["TG_SESSION_STRING"]      # gere uma vez, ver gerar_sessao.py

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # SERVICE ROLE (ignora RLS)

GEMINI_KEY  = os.environ["GEMINI_API_KEY"]
MODO        = os.environ.get("MODO", "live")        # "live" ou "polling"

# ============================================================
# CLIENTES
# ============================================================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")

client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)


# ============================================================
# EXTRAÇÃO - usa o Gemini para estruturar a promoção
# ============================================================
PROMPT = """Você recebe o texto de uma mensagem de um canal de promoções.
Extraia os dados e responda APENAS com um JSON válido, sem markdown, no formato:
{{"titulo": "...", "preco": 0.0, "preco_original": 0.0 ou null,
  "cupom": "..." ou null, "link": "..." ou null, "categoria": "..."}}

A categoria deve ser uma destas: eletronicos, casa, moda, alimentos, beleza, games, outros.
Se não for uma promoção de produto, responda exatamente: {{"ignorar": true}}

Texto da mensagem:
\"\"\"{texto}\"\"\""""


async def extrair_produto(texto: str) -> dict | None:
    """Pede ao Gemini para estruturar o texto. Retorna dict ou None."""
    try:
        resp = await asyncio.to_thread(
            gemini.generate_content, PROMPT.format(texto=texto)
        )
        raw = resp.text.strip()
        raw = re.sub(r"^```json|```$", "", raw).strip()  # remove cercas
        data = json.loads(raw)
        if data.get("ignorar"):
            return None
        return data
    except Exception as e:
        print(f"[gemini] erro ao extrair: {e}")
        return None


# ============================================================
# FILTROS - aplica as regras cadastradas no Supabase
# ============================================================
def carregar_filtros() -> list[dict]:
    res = supabase.table("filtros").select("*").eq("ativo", True).execute()
    return res.data or []


def passa_no_filtro(produto: dict, filtros: list[dict]) -> bool:
    """Se não há filtros, aceita tudo. Senão, precisa passar em ao menos um."""
    if not filtros:
        return True
    titulo = (produto.get("titulo") or "").lower()
    preco = produto.get("preco") or 0
    for f in filtros:
        # bloqueio
        if any(b.lower() in titulo for b in (f.get("palavras_bloqueio") or [])):
            continue
        # categoria
        if f.get("categoria") and f["categoria"] != produto.get("categoria"):
            continue
        # preço máximo
        if f.get("preco_max") and preco > float(f["preco_max"]):
            continue
        # palavras-chave (se houver, ao menos uma precisa bater)
        chaves = f.get("palavras_chave") or []
        if chaves and not any(c.lower() in titulo for c in chaves):
            continue
        return True
    return False


# ============================================================
# STORAGE - sobe a foto para o bucket do Supabase
# ============================================================
async def subir_foto(msg) -> str | None:
    """Baixa a mídia da mensagem e sobe para o Storage. Retorna URL pública."""
    if not msg.photo:
        return None
    try:
        caminho = await msg.download_media(file="/tmp/")
        nome = f"{msg.chat_id}_{msg.id}.jpg"
        with open(caminho, "rb") as fp:
            supabase.storage.from_("produtos").upload(
                nome, fp, {"content-type": "image/jpeg", "upsert": "true"}
            )
        os.remove(caminho)
        return supabase.storage.from_("produtos").get_public_url(nome)
    except Exception as e:
        print(f"[storage] erro ao subir foto: {e}")
        return None


# ============================================================
# SALVAR - grava o produto no banco (ignora duplicados)
# ============================================================
async def processar_mensagem(msg, canal: str, filtros: list[dict]):
    texto = msg.text or msg.message or ""
    if not texto:
        return

    produto = await extrair_produto(texto)
    if not produto:
        return
    if not passa_no_filtro(produto, filtros):
        print(f"[filtro] descartado: {produto.get('titulo')}")
        return

    foto_url = await subir_foto(msg)

    registro = {
        "titulo": produto.get("titulo"),
        "preco": produto.get("preco"),
        "preco_original": produto.get("preco_original"),
        "cupom": produto.get("cupom"),
        "link": produto.get("link"),
        "categoria": produto.get("categoria", "outros"),
        "foto_url": foto_url,
        "canal_origem": canal,
        "telegram_msg_id": msg.id,
        "raw_text": texto[:2000],
    }
    try:
        supabase.table("produtos").upsert(
            registro, on_conflict="canal_origem,telegram_msg_id"
        ).execute()
        print(f"[ok] salvo: {registro['titulo']}")
    except Exception as e:
        print(f"[db] erro ao salvar: {e}")


# ============================================================
# MODO LIVE - conexão persistente (para VPS)
# ============================================================
async def rodar_live():
    canais = supabase.table("canais").select("username").eq("ativo", True).execute()
    usernames = [c["username"] for c in (canais.data or [])]
    if not usernames:
        print("[aviso] nenhum canal cadastrado")
        return

    print(f"[live] monitorando: {usernames}")

    @client.on(events.NewMessage(chats=usernames))
    async def handler(event):
        filtros = carregar_filtros()
        canal = event.chat.username or str(event.chat_id)
        await processar_mensagem(event.message, canal, filtros)

    await client.run_until_disconnected()


# ============================================================
# MODO POLLING - roda uma vez e sai (para cron/GitHub Actions)
# ============================================================
async def rodar_polling():
    filtros = carregar_filtros()
    canais = supabase.table("canais").select("username").eq("ativo", True).execute()

    for c in (canais.data or []):
        canal = c["username"]
        # pega o último msg_id já processado
        st = supabase.table("bot_state").select("last_msg_id") \
            .eq("canal_username", canal).execute()
        last_id = st.data[0]["last_msg_id"] if st.data else 0

        novo_last = last_id
        async for msg in client.iter_messages(canal, min_id=last_id, limit=50):
            await processar_mensagem(msg, canal, filtros)
            novo_last = max(novo_last, msg.id)

        # atualiza o state
        supabase.table("bot_state").upsert({
            "canal_username": canal,
            "last_msg_id": novo_last,
        }).execute()
        print(f"[polling] {canal}: até msg {novo_last}")


# ============================================================
# MAIN
# ============================================================
async def main():
    await client.start()
    if MODO == "polling":
        await rodar_polling()
    else:
        await rodar_live()


if __name__ == "__main__":
    asyncio.run(main())
