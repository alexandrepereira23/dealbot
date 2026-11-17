"""Backup online SQLite e restauração explícita em diretório NOVO; sem ler .env."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

TABELAS = ("canais", "eventos", "donos_hash", "midias", "resolucoes", "cache_urls", "enriquecimentos")


def privado(diretorio):
    if not diretorio.is_absolute() or not diretorio.is_dir() or diretorio.is_symlink():
        raise ValueError("diretorio_privado_ausente")
    if os.name == "posix" and diretorio.stat().st_mode & 0o077:
        raise ValueError("diretorio_deve_ser_0700")


def leitura(caminho):
    if caminho.is_symlink() or not caminho.is_file():
        raise ValueError("sqlite_ausente_ou_link")
    return sqlite3.connect(caminho.as_uri() + "?mode=ro", uri=True, timeout=10)


def resumo(caminho):
    with closing(leitura(caminho)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("sqlite_corrompido")
        versao = db.execute("PRAGMA user_version").fetchone()[0]
        if versao not in range(1, 8):
            raise ValueError("sqlite_versao_nao_suportada")
        tabelas = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        dados = {}
        for tabela in TABELAS:
            if tabela not in tabelas:
                # Versões antigas podem não possuir enriquecimentos/cache.
                continue
            digest = hashlib.sha256()
            quantidade = 0
            for linha in db.execute(f'SELECT * FROM "{tabela}" ORDER BY rowid'):
                digest.update(json.dumps(linha, ensure_ascii=True, separators=(",", ":")).encode())
                digest.update(b"\n")
                quantidade += 1
            dados[tabela] = {"quantidade": quantidade, "sha256": digest.hexdigest()}
        if not {"canais", "eventos", "midias"}.issubset(dados):
            raise ValueError("sqlite_nao_e_estado_dealbot")
    return {"versao": versao, "tabelas": dados}


def sha256(caminho):
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def criar_exclusivo(caminho):
    return os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)


def sincronizar_diretorio(diretorio):
    if os.name == "posix":
        fd = os.open(diretorio, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def manifesto_de(caminho):
    return caminho.with_name(caminho.name + ".manifest.json")


def verificar(backup):
    meta = json.loads(manifesto_de(backup).read_text(encoding="utf-8"))
    if sha256(backup) != meta["arquivo_sha256"] or resumo(backup) != meta["estado"]:
        raise ValueError("backup_divergente")
    return meta


def salvar(origem, destino):
    privado(destino.parent)
    if origem == destino or origem.parent == destino.parent:
        raise ValueError("backup_deve_ficar_fora_do_estado")
    if manifesto_de(destino).exists():
        raise ValueError("manifesto_existente")
    # Preflight antes de criar o destino; não cria SQLite vazio se a origem faltar.
    with closing(leitura(origem)) as fonte:
        os.close(criar_exclusivo(destino))
        with closing(sqlite3.connect(destino)) as copia:
            fonte.backup(copia, pages=256, sleep=0.05)
            copia.execute("PRAGMA journal_mode=DELETE")
    meta = {"formato": 1, "arquivo_sha256": sha256(destino), "estado": resumo(destino)}
    with os.fdopen(criar_exclusivo(manifesto_de(destino)), "w", encoding="utf-8") as arquivo:
        json.dump(meta, arquivo, sort_keys=True)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    with destino.open("r+b") as arquivo:
        os.fsync(arquivo.fileno())
    sincronizar_diretorio(destino.parent)
    verificar(destino)


def restaurar(backup, diretorio):
    meta = verificar(backup)
    if not diretorio.is_absolute() or not diretorio.parent.is_dir():
        raise ValueError("pai_de_restauracao_ausente")
    diretorio.mkdir(mode=0o700)  # Sem exist_ok: nunca sobrescrever fila existente.
    destino = diretorio / "inbox.sqlite3"
    with os.fdopen(criar_exclusivo(destino), "wb") as arquivo, backup.open("rb") as origem:
        shutil.copyfileobj(origem, arquivo)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    if resumo(destino) != meta["estado"] or sha256(destino) != meta["arquivo_sha256"]:
        raise ValueError("restauracao_divergente")
    sincronizar_diretorio(diretorio)
    sincronizar_diretorio(diretorio.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="acao", required=True)
    salvar_cli = sub.add_parser("backup")
    salvar_cli.add_argument("origem", type=Path)
    salvar_cli.add_argument("destino", type=Path)
    verificar_cli = sub.add_parser("verify")
    verificar_cli.add_argument("backup", type=Path)
    restaurar_cli = sub.add_parser("restore")
    restaurar_cli.add_argument("backup", type=Path)
    restaurar_cli.add_argument("diretorio_novo", type=Path)
    args = parser.parse_args()
    try:
        if args.acao == "backup":
            salvar(args.origem.absolute(), args.destino.absolute())
        elif args.acao == "verify":
            verificar(args.backup.absolute())
        else:
            restaurar(args.backup.absolute(), args.diretorio_novo.absolute())
    except Exception:
        print("backup: falha; conferir integridade, permissões e destinos sem sobrescrever dados", file=sys.stderr)
        return 1
    print(f"backup: {args.acao} verificado (conteúdo privado omitido)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
