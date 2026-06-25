"""
Gera a SESSION STRING do Telethon — rode UMA vez, localmente.
  python gerar_sessao.py
Cole o resultado na variável TG_SESSION_STRING.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API ID: "))
api_hash = input("API HASH: ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\n=== SUA SESSION STRING (guarde com segurança) ===\n")
    print(client.session.save())
    print("\n=================================================")
