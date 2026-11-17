"""Ensaio de arquivo/restauração de bytes no volume sintético Linux."""
import hashlib
import os
from pathlib import Path
import tarfile

assert os.getuid() == 10001
origem = Path("/data/media")
backup = Path("/backup")
hashes = lambda raiz: {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in raiz.glob("*.webp")}
antes = hashes(origem)
assert antes
with tarfile.open(backup / "media.tar.gz", "x:gz") as arquivo:
    arquivo.add(origem, arcname="media")
destino = backup / "media-restaurada"
destino.mkdir(mode=0o700)
with tarfile.open(backup / "media.tar.gz") as arquivo:
    arquivo.extractall(destino, filter="data")
assert antes == hashes(destino / "media")
print("backup: arquivo/restauração de mídia sintética e hashes aprovados")
