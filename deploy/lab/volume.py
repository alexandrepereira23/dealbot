"""Executar SOMENTE no volume dedicado do laboratório Compose."""
import asyncio
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from PIL import Image
from src.midia import ArmazenamentoLocal


ESTADO = Path("/data/state")
MIDIA = Path("/data/media")


def verificar(caminho, tipo, uid, gid, modo):
    info = caminho.lstat()
    atual = (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
    assert tipo(info.st_mode) and atual == (uid, gid, modo), (
        f"{caminho}: esperado {uid}:{gid} {modo:04o}, lido {atual[0]}:{atual[1]} {atual[2]:04o}"
    )


def verificar_estado():
    verificar(ESTADO, stat.S_ISDIR, 10001, 10000, 0o700)
    for nome in ("coletor.lock", "inbox.sqlite3", "inbox.sqlite3-wal", "inbox.sqlite3-shm"):
        verificar(ESTADO / nome, stat.S_ISREG, 10001, 10000, 0o600)


def fila():
    # Lê o SQLite em execução sem modificar o claim ou inicializar um novo banco.
    with closing(sqlite3.connect((ESTADO / "inbox.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        linhas = db.execute("""SELECT produto_id, canal_id, msg_id, chave, destino, estado,
            tentativas, enviado, url FROM midias ORDER BY produto_id""").fetchall()
    print(json.dumps([dict(linha) for linha in linhas]))


async def publicar_orfa():
    raiz = MIDIA
    local = ArmazenamentoLocal(raiz, max_entrada=10485760, max_pixels=24000000,
        lado_max=960, max_saida=358400)
    try:
        await local.preparar()
        entrada = io.BytesIO()
        Image.new("RGB", (60, 30), "#2277aa").save(entrada, format="JPEG")
        chave = "f" * 32 + ".webp"
        await local.enviar(chave, entrada.getvalue())
        verificar(raiz / chave, stat.S_ISREG, 10001, 10000, 0o640)
    finally:
        await local.fechar()


if __name__ == "__main__":
    assert (os.geteuid(), os.getegid()) == (10001, 10000), "UID/GID efetivos do bot"
    if sys.argv[1:] == ["--fila"]:
        fila()
    else:
        assert sys.argv[1:] in ([], ["--somente-estado"])
        verificar_estado()
        verificar(MIDIA, stat.S_ISDIR, 10001, 10000, 0o2770)
        verificar(Path("/backup"), stat.S_ISDIR, 10001, 10000, 0o700)
        if not sys.argv[1:]:
            asyncio.run(publicar_orfa())
        print("volume: modos e proprietários exatos como bot (estado privado e mídia compartilhada)")
