"""Fingerprint de campos congelados da fixture; nunca imprime texto/URL/segredo."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def fingerprint(diretorio):
    caminho = diretorio / "inbox.sqlite3"
    with closing(sqlite3.connect(caminho.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        eventos = db.execute("SELECT canal_id,msg_id,decisao,hash,identidade,produto_id FROM eventos ORDER BY canal_id,msg_id").fetchall()
        midias = db.execute("SELECT produto_id,canal_id,msg_id,chave,destino FROM midias ORDER BY produto_id").fetchall()
        canais = db.execute("SELECT canal_id,cursor,bootstrap FROM canais ORDER BY canal_id").fetchall()
        assert eventos and midias
        return hashlib.sha256(json.dumps([eventos, midias, canais], sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    print(fingerprint(Path(os.environ["BOT_STATE_DIR"])))
