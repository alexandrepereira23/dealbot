"""Inbox SQLite: um proprietário, um executor e commits antes da confirmação."""

import asyncio
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .modelos import FalhaLocal, Mensagem, normalizar_username

TERMINAIS = ("aprovada", "duplicata", "descartada", "falha_permanente")
MIDIA_TERMINAIS = ("pronta", "sem_foto", "falha_permanente", "removida")


class EstadoLocal:
    """Todas as operações SQLite ocorrem no mesmo thread, com submissão limitada."""

    def __init__(self, diretorio: Path, buffer_max: int = 100, cota_live: int = 4) -> None:
        self.diretorio = diretorio
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")
        self._gate = asyncio.Semaphore(buffer_max)
        self._cota_live = cota_live
        self._escolhas_live = 0
        self._ultimo_canal_historico = 0
        self._ultimo_canal_live = 0
        self.db: sqlite3.Connection | None = None
        self._lock: Any = None
        self._fechado = False

    async def _executar(self, fn: Callable[..., Any], *args: Any) -> Any:
        async with self._gate:
            futuro = asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)
            try:
                return await asyncio.shield(futuro)
            except asyncio.CancelledError:
                # Cancelar a espera não cancela um commit. Drenar antes de liberar gate/lock.
                try:
                    await futuro
                except (sqlite3.Error, OSError):
                    pass
                raise
            except (sqlite3.Error, OSError) as erro:
                raise FalhaLocal(type(erro).__name__) from erro

    async def abrir(self) -> None:
        """Abre armazenamento privado, rejeita segunda instância e recupera claims."""
        try:
            await self._executar(self._abrir)
        except BaseException:
            await self.fechar()
            raise

    def _abrir(self) -> None:
        self.diretorio.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.diretorio.chmod(0o700)
        lock_path = self.diretorio / "coletor.lock"
        self._lock = open(lock_path, "a+b")
        self._lock.seek(0, os.SEEK_END)
        if self._lock.tell() == 0:
            self._lock.write(b"0")
            self._lock.flush()
        self._lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db = sqlite3.connect(self.diretorio / "inbox.sqlite3", timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=2000")
        versao = self.db.execute("PRAGMA user_version").fetchone()[0]
        if versao not in (0, 1, 2, 3, 4):
            raise FalhaLocal("versao_local_nao_suportada")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS canais (
                canal_id INTEGER PRIMARY KEY, username TEXT NOT NULL, access_hash TEXT,
                aliases TEXT NOT NULL DEFAULT '[]', cursor INTEGER NOT NULL DEFAULT 0,
                bootstrap REAL NOT NULL, limite INTEGER, proxima REAL NOT NULL DEFAULT 0,
                tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT, ativo INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS eventos (
                canal_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, username TEXT NOT NULL,
                remoto_canal TEXT NOT NULL, texto TEXT NOT NULL, data_origem TEXT NOT NULL,
                recebido_em REAL NOT NULL, origem TEXT NOT NULL, tem_foto INTEGER NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendente', tentativas INTEGER NOT NULL DEFAULT 0,
                proxima REAL NOT NULL DEFAULT 0, erro TEXT, decisao TEXT, hash TEXT,
                produto_id INTEGER, resultado TEXT, finalizado_em REAL, disponibilizado_em REAL,
                PRIMARY KEY(canal_id,msg_id)
            );
            CREATE INDEX IF NOT EXISTS ix_eventos_elegiveis ON eventos(estado,proxima,origem,recebido_em);
            CREATE TABLE IF NOT EXISTS donos_hash (
                hash TEXT PRIMARY KEY, canal_id INTEGER NOT NULL, msg_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS midias (
                produto_id INTEGER PRIMARY KEY, canal_id INTEGER NOT NULL, msg_id INTEGER NOT NULL,
                chave TEXT NOT NULL UNIQUE, estado TEXT NOT NULL DEFAULT 'pendente',
                tentativas INTEGER NOT NULL DEFAULT 0, proxima REAL NOT NULL DEFAULT 0,
                erro TEXT, url TEXT, enviado INTEGER NOT NULL DEFAULT 0,
                compensar INTEGER NOT NULL DEFAULT 0, finalizado_em REAL, falha_apos_limpeza TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_midias_elegiveis ON midias(estado,proxima);
            CREATE TABLE IF NOT EXISTS resolucoes (
                username TEXT PRIMARY KEY, proxima REAL NOT NULL DEFAULT 0,
                tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT
            );
        """)
        if "disponibilizado_em" not in {r[1] for r in self.db.execute("PRAGMA table_info(eventos)")}:
            self.db.execute("ALTER TABLE eventos ADD COLUMN disponibilizado_em REAL")
        if "falha_apos_limpeza" not in {r[1] for r in self.db.execute("PRAGMA table_info(midias)")}:
            self.db.execute("ALTER TABLE midias ADD COLUMN falha_apos_limpeza TEXT")
        if "geracao" not in {r[1] for r in self.db.execute("PRAGMA table_info(canais)")}:
            self.db.execute("ALTER TABLE canais ADD COLUMN geracao INTEGER NOT NULL DEFAULT 0")
        self.db.execute("PRAGMA user_version=4")
        with self.db:
            self.db.execute("UPDATE eventos SET estado='retry' WHERE estado='processando'")
            self.db.execute("UPDATE midias SET estado='retry' WHERE estado='processando'")
        if os.name != "nt":
            for caminho in self.diretorio.iterdir():
                if caminho.is_file():
                    caminho.chmod(0o600)

    def _conexao(self) -> sqlite3.Connection:
        if self.db is None:
            raise FalhaLocal("estado_nao_aberto")
        return self.db

    def _inserir(self, msg: Mensagem) -> bool:
        db = self._conexao()
        username = normalizar_username(msg.username) or str(msg.canal_id)
        res = db.execute("""INSERT OR IGNORE INTO eventos
            (canal_id,msg_id,username,remoto_canal,texto,data_origem,recebido_em,origem,tem_foto)
            VALUES (?,?,?,?,?,?,?,?,?)""", (msg.canal_id, msg.msg_id, username, username,
            msg.texto, msg.data_origem, msg.recebido_em, msg.origem, int(msg.tem_foto)))
        novo = res.rowcount == 1
        if msg.origem == "live":
            db.execute("""UPDATE eventos SET origem='live' WHERE canal_id=? AND msg_id=?
                AND estado IN ('pendente','retry','aguardando_config')""", (msg.canal_id, msg.msg_id))
        return novo

    async def registrar(self, msg: Mensagem, geracao: int | None = None) -> bool | None:
        """Aceita evento sem mover fronteira; None rejeita ativação já encerrada.

        Inbox também atende entradas locais sem cadastro de canal (testes e
        retomada offline). Quando cadastrado, ativo/geração e inserção são uma
        única operação serial, igual à proteção usada nas páginas históricas.
        """
        def op() -> bool | None:
            db = self._conexao()
            with db:
                canal = db.execute("SELECT ativo,geracao FROM canais WHERE canal_id=?", (msg.canal_id,)).fetchone()
                if canal is not None and (not canal["ativo"] or (geracao is not None and canal["geracao"] != geracao)):
                    return None
                return self._inserir(msg)
        return await self._executar(op)

    async def registrar_pagina(self, canal_id: int, mensagens: list[Mensagem], cursor: int,
                               esgotou: bool, proxima: float, geracao: int | None = None) -> int | None:
        """A página e cobertura comprovada avançam juntas, mesmo se todos forem duplicados."""
        def op() -> int | None:
            db = self._conexao()
            with db:
                canal = db.execute("SELECT ativo,geracao FROM canais WHERE canal_id=?", (canal_id,)).fetchone()
                if canal is None or not canal["ativo"] or (geracao is not None and canal["geracao"] != geracao):
                    return None
                novos = sum(self._inserir(msg) for msg in mensagens)
                db.execute("""UPDATE canais SET cursor=MAX(cursor,?),
                    limite=CASE WHEN ? THEN NULL ELSE limite END,
                    proxima=?,tentativas=0,erro=NULL WHERE canal_id=?""",
                    (cursor, esgotou, proxima, canal_id))
                return novos
        return await self._executar(op)

    async def configurar_canal(self, canal_id: int, username: str, access_hash: int | None,
                               bootstrap: float, aliases_extras: list[str] | None = None,
                               ativar: bool = True) -> None:
        def op() -> None:
            db = self._conexao()
            anterior = db.execute("SELECT aliases FROM canais WHERE canal_id=?", (canal_id,)).fetchone()
            aliases = json.loads(anterior[0]) if anterior else []
            for alias in (username, normalizar_username(username), "@" + normalizar_username(username), *(aliases_extras or [])):
                if alias not in aliases:
                    aliases.append(alias)
            with db:
                db.execute("""INSERT INTO canais(canal_id,username,access_hash,aliases,bootstrap,ativo)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(canal_id) DO UPDATE SET
                    username=excluded.username,access_hash=COALESCE(excluded.access_hash,canais.access_hash),
                    aliases=excluded.aliases,
                    geracao=canais.geracao+CASE WHEN ? AND canais.ativo=0 THEN 1 ELSE 0 END,
                    ativo=CASE WHEN ? THEN 1 ELSE canais.ativo END""",
                    (canal_id, normalizar_username(username), str(access_hash) if access_hash is not None else None,
                     json.dumps(aliases), bootstrap, int(ativar), ativar, ativar))
        await self._executar(op)

    async def ativar_canais(self, ids: list[int]) -> None:
        def op() -> None:
            db = self._conexao()
            with db:
                ativos = set(ids)
                for canal in db.execute("SELECT canal_id,ativo FROM canais").fetchall():
                    ativo = int(canal["canal_id"] in ativos)
                    if canal["ativo"] != ativo:
                        db.execute("UPDATE canais SET ativo=?,geracao=geracao+1 WHERE canal_id=?",
                                   (ativo, canal["canal_id"]))
        await self._executar(op)

    async def resolucao(self, username: str) -> dict | None:
        def op() -> dict | None:
            linha = self._conexao().execute("SELECT * FROM resolucoes WHERE username=?",
                                            (normalizar_username(username),)).fetchone()
            return dict(linha) if linha else None
        return await self._executar(op)

    async def falhar_resolucao(self, username: str, proxima: float, erro: str) -> None:
        """Checkpoint anterior ao ID Telegram; recebe somente motivo classificado."""
        def op() -> None:
            with self._conexao():
                self._conexao().execute("""INSERT INTO resolucoes(username,proxima,tentativas,erro)
                    VALUES(?,?,1,?) ON CONFLICT(username) DO UPDATE SET
                    proxima=MAX(resolucoes.proxima,excluded.proxima),
                    tentativas=resolucoes.tentativas+1,erro=excluded.erro""",
                    (normalizar_username(username), proxima, erro))
        await self._executar(op)

    async def concluir_resolucao(self, username: str) -> None:
        def op() -> None:
            with self._conexao():
                self._conexao().execute("DELETE FROM resolucoes WHERE username=?", (normalizar_username(username),))
        await self._executar(op)

    async def canais(self) -> list[dict]:
        return await self._executar(lambda: [dict(r) for r in self._conexao().execute("SELECT * FROM canais ORDER BY canal_id")])

    async def canal(self, canal_id: int) -> dict | None:
        def op() -> dict | None:
            linha = self._conexao().execute("SELECT * FROM canais WHERE canal_id=?", (canal_id,)).fetchone()
            return dict(linha) if linha else None
        return await self._executar(op)

    async def aliases(self, canal_id: int) -> list[str]:
        def op() -> list[str]:
            linha = self._conexao().execute("SELECT aliases FROM canais WHERE canal_id=?", (canal_id,)).fetchone()
            return json.loads(linha[0]) if linha else []
        return await self._executar(op)

    async def iniciar_varredura(self, canal_id: int, limite: int, geracao: int | None = None) -> bool:
        def op() -> bool:
            with self._conexao():
                res = self._conexao().execute("""UPDATE canais SET limite=? WHERE canal_id=?
                    AND limite IS NULL AND ativo=1 AND (? IS NULL OR geracao=?)""", (limite, canal_id, geracao, geracao))
                return res.rowcount == 1
        return await self._executar(op)

    async def falhar_canal(self, canal_id: int, proxima: float, erro: str, geracao: int | None = None,
                           minimo_remoto: bool = False) -> None:
        def op() -> None:
            with self._conexao():
                if minimo_remoto:
                    # O limite pertence ao canal estável, não à sua ativação.
                    # Um RPC antigo pode receber FloodWait depois de desativar/
                    # reativar; conservar o prazo sem tocar cobertura/ativação.
                    self._conexao().execute("""UPDATE canais SET proxima=MAX(proxima,?),
                        erro=?,tentativas=tentativas+1 WHERE canal_id=?""", (proxima, erro, canal_id))
                else:
                    self._conexao().execute("""UPDATE canais SET proxima=?,erro=?,tentativas=tentativas+1
                        WHERE canal_id=? AND ativo=1 AND (? IS NULL OR geracao=?)""", (proxima, erro, canal_id, geracao, geracao))
        await self._executar(op)

    async def acordar_canais(self) -> None:
        def op() -> None:
            with self._conexao():
                # Não antecipar FloodWait/backoff persistido.
                self._conexao().execute("UPDATE canais SET proxima=0 WHERE erro IS NULL")
        await self._executar(op)

    async def obter_oferta(self, agora: float, config_valida: bool) -> dict | None:
        def op() -> dict | None:
            db = self._conexao()
            with db:
                estados = "('pendente','retry','aguardando_config')" if config_valida else "('pendente','retry')"
                base = f"SELECT * FROM eventos WHERE estado IN {estados} AND proxima<=?"
                historico = self._escolhas_live >= self._cota_live
                classes = ("historico", "live") if historico else ("live", "historico")
                linha = None
                for origem in classes:
                    linha = db.execute(base + " AND origem=? ORDER BY CASE WHEN canal_id>? THEN 0 ELSE 1 END,canal_id,recebido_em,msg_id LIMIT 1",
                                       (agora, origem, self._ultimo_canal_historico if origem == "historico" else self._ultimo_canal_live)).fetchone()
                    if linha:
                        break
                if not linha:
                    return None
                self._escolhas_live = self._escolhas_live + 1 if linha["origem"] == "live" else 0
                if linha["origem"] == "historico":
                    self._ultimo_canal_historico = linha["canal_id"]
                else:
                    self._ultimo_canal_live = linha["canal_id"]
                db.execute("UPDATE eventos SET estado='processando',tentativas=tentativas+1 WHERE canal_id=? AND msg_id=?", (linha["canal_id"], linha["msg_id"]))
                resultado = dict(linha)
                resultado["tentativas"] += 1
                return resultado
        return await self._executar(op)

    async def decidir(self, job: dict, produto: dict, hash_oferta: str) -> None:
        def op() -> None:
            with self._conexao():
                self._conexao().execute("UPDATE eventos SET decisao=?,hash=? WHERE canal_id=? AND msg_id=?",
                                         (json.dumps(produto), hash_oferta, job["canal_id"], job["msg_id"]))
        await self._executar(op)

    async def reservar_hash(self, job: dict, hash_oferta: str) -> bool:
        def op() -> bool:
            db = self._conexao()
            with db:
                db.execute("INSERT OR IGNORE INTO donos_hash VALUES(?,?,?)", (hash_oferta, job["canal_id"], job["msg_id"]))
                dono = db.execute("SELECT canal_id,msg_id FROM donos_hash WHERE hash=?", (hash_oferta,)).fetchone()
                return tuple(dono) == (job["canal_id"], job["msg_id"])
        return await self._executar(op)

    async def vincular(self, job: dict, produto_id: int) -> None:
        def op() -> None:
            with self._conexao():
                self._conexao().execute("""UPDATE eventos SET produto_id=?,
                    disponibilizado_em=COALESCE(disponibilizado_em,?) WHERE canal_id=? AND msg_id=?""",
                    (produto_id, time.time(), job["canal_id"], job["msg_id"]))
        await self._executar(op)

    async def finalizar_oferta(self, job: dict, estado: str, produto_id: int | None = None,
                               midia: bool = False, resultado: str | None = None) -> None:
        def op() -> None:
            db = self._conexao()
            with db:
                db.execute("""UPDATE eventos SET estado=?,produto_id=COALESCE(?,produto_id),
                    resultado=?,erro=CASE WHEN ?='falha_permanente' THEN ? ELSE NULL END,
                    finalizado_em=? WHERE canal_id=? AND msg_id=?""",
                    (estado, produto_id, resultado, estado, resultado, time.time(), job["canal_id"], job["msg_id"]))
                db.execute("DELETE FROM donos_hash WHERE canal_id=? AND msg_id=?", (job["canal_id"], job["msg_id"]))
                if midia and produto_id is not None:
                    chave = f"{produto_id}_{job['canal_id']}_{job['msg_id']}.jpg"
                    db.execute("INSERT OR IGNORE INTO midias(produto_id,canal_id,msg_id,chave) VALUES(?,?,?,?)",
                               (produto_id, job["canal_id"], job["msg_id"], chave))
        await self._executar(op)

    async def adiar_oferta(self, job: dict, estado: str, proxima: float, erro: str) -> None:
        def op() -> None:
            with self._conexao():
                self._conexao().execute("UPDATE eventos SET estado=?,proxima=?,erro=? WHERE canal_id=? AND msg_id=?",
                                         (estado, proxima, erro, job["canal_id"], job["msg_id"]))
        await self._executar(op)

    async def obter_midia(self, agora: float) -> dict | None:
        def op() -> dict | None:
            db = self._conexao()
            with db:
                linha = db.execute("SELECT * FROM midias WHERE estado IN ('pendente','retry') AND proxima<=? ORDER BY proxima,produto_id LIMIT 1", (agora,)).fetchone()
                if not linha:
                    return None
                db.execute("UPDATE midias SET estado='processando',tentativas=tentativas+1 WHERE produto_id=?", (linha["produto_id"],))
                job = dict(linha)
                job["tentativas"] += 1
                return job
        return await self._executar(op)

    async def atualizar_midia(self, produto_id: int, **campos: Any) -> None:
        permitidos = {"estado", "proxima", "erro", "url", "enviado", "compensar", "finalizado_em", "falha_apos_limpeza"}
        if not campos or not set(campos) <= permitidos:
            raise ValueError("campos_de_midia_invalidos")
        def op() -> None:
            with self._conexao():
                self._conexao().execute("UPDATE midias SET " + ",".join(f"{k}=?" for k in campos) + " WHERE produto_id=?", (*campos.values(), produto_id))
        await self._executar(op)

    async def proxima_tentativa(self, classe: str, config_valida: bool = True) -> float | None:
        def op() -> float | None:
            tabela = "eventos" if classe == "oferta" else "midias"
            estados = "('pendente','retry','aguardando_config')" if classe == "oferta" and config_valida else "('pendente','retry')"
            return self._conexao().execute(f"SELECT MIN(proxima) FROM {tabela} WHERE estado IN {estados}").fetchone()[0]
        return await self._executar(op)

    async def limpar(self, antes: float, lote: int = 100) -> dict[str, int]:
        """Uma transação curta; contagens independentes para controlar a drenagem."""
        if type(lote) is not int or not 1 <= lote <= 1000:
            raise ValueError("lote de limpeza precisa ser inteiro entre 1 e 1000")
        def op() -> dict[str, int]:
            db = self._conexao()
            with db:
                # Não apagar a fonte de mídia recuperável, mesmo se sua oferta já terminou.
                ids = db.execute("""SELECT canal_id,msg_id FROM eventos e WHERE
                    estado IN ('aprovada','duplicata','descartada','falha_permanente') AND finalizado_em<?
                    AND NOT EXISTS(SELECT 1 FROM midias m WHERE m.produto_id=e.produto_id
                        AND (m.estado NOT IN ('pronta','sem_foto','falha_permanente','removida') OR m.compensar=1))
                    AND NOT EXISTS(SELECT 1 FROM donos_hash d WHERE d.canal_id=e.canal_id AND d.msg_id=e.msg_id)
                    LIMIT ?""", (antes, lote)).fetchall()
                db.executemany("DELETE FROM eventos WHERE canal_id=? AND msg_id=?", [tuple(r) for r in ids])
                midias = db.execute("""DELETE FROM midias WHERE produto_id IN (SELECT produto_id FROM midias
                    WHERE estado IN ('pronta','sem_foto','falha_permanente','removida') AND compensar=0
                    AND finalizado_em<? LIMIT ?)""", (antes, lote))
                return {"eventos": len(ids), "midias": midias.rowcount}
        return await self._executar(op)

    async def resumo(self) -> dict:
        def op() -> dict:
            db = self._conexao()
            return {"ofertas": {r[0]: r[1] for r in db.execute("SELECT estado,COUNT(*) FROM eventos GROUP BY estado")},
                    "midias": {r[0]: r[1] for r in db.execute("SELECT estado,COUNT(*) FROM midias GROUP BY estado")},
                    "mais_antiga": db.execute("SELECT MIN(recebido_em) FROM eventos WHERE finalizado_em IS NULL").fetchone()[0]}
        return await self._executar(op)

    async def evento(self, canal_id: int, msg_id: int) -> dict | None:
        def op() -> dict | None:
            linha = self._conexao().execute("SELECT * FROM eventos WHERE canal_id=? AND msg_id=?", (canal_id, msg_id)).fetchone()
            return dict(linha) if linha else None
        return await self._executar(op)

    async def midia(self, produto_id: int) -> dict | None:
        def op() -> dict | None:
            linha = self._conexao().execute("SELECT * FROM midias WHERE produto_id=?", (produto_id,)).fetchone()
            return dict(linha) if linha else None
        return await self._executar(op)

    async def fechar(self) -> None:
        """Drena executor antes de fechar banco e liberar proprietário do diretório."""
        if self._fechado:
            return
        def op() -> None:
            if self.db is not None:
                self.db.close()
                self.db = None
            if self._lock is not None:
                self._lock.close()
                self._lock = None
        await self._executar(op)
        self.executor.shutdown(wait=True)
        self._fechado = True
