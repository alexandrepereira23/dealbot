"""
DEALBOT - Bot de monitoramento de promoções (modo live / persistente)
"""
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .config import Config
from .extractor import extrair_produto
from .filters import carregar_filtros, passa_no_filtro
from .repository import subir_foto, salvar_produto, listar_canais

client = TelegramClient(
    StringSession(Config.TG_SESSION_STRING),
    Config.TG_API_ID,
    Config.TG_API_HASH,
)


async def processar(msg, canal: str, filtros: list[dict]):
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
    if salvar_produto(registro):
        print(f"[ok] salvo: {registro['titulo']}")


async def handler(event):
    """Processa cada mensagem em task separada — não bloqueia as próximas."""
    filtros = carregar_filtros()
    canal = getattr(event.chat, "username", None) or str(event.chat_id)
    asyncio.create_task(processar(event.message, canal, filtros))


async def main():
    await client.start()

    canais = listar_canais()
    if not canais:
        print("[aviso] nenhum canal cadastrado. Adicione na tabela 'canais'.")
        return

    print(f"[live] monitorando: {canais}")

    client.add_event_handler(handler, events.NewMessage(chats=canais))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())