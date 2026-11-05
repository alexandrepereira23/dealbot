"""Fixtures sintéticas: metadados locais e migração real SQLite, sem rede."""

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

from src.estado import EstadoLocal
from src.modelos import FalhaLocal, Mensagem
from src.telegram import Telegram

DATA = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
CANAL = -1000000000111
TEM_TELETHON = importlib.util.find_spec("telethon") is not None

# DDL da versão anterior, deliberadamente sem contexto/diagnostico. Não usar o
# inicializador novo para fabricar um banco supostamente antigo.
SCHEMA_V4 = """
CREATE TABLE canais (
 canal_id INTEGER PRIMARY KEY, username TEXT NOT NULL, access_hash TEXT,
 aliases TEXT NOT NULL DEFAULT '[]', cursor INTEGER NOT NULL DEFAULT 0,
 bootstrap REAL NOT NULL, limite INTEGER, proxima REAL NOT NULL DEFAULT 0,
 tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT, ativo INTEGER NOT NULL DEFAULT 1,
 geracao INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE eventos (
 canal_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, username TEXT NOT NULL,
 remoto_canal TEXT NOT NULL, texto TEXT NOT NULL, data_origem TEXT NOT NULL,
 recebido_em REAL NOT NULL, origem TEXT NOT NULL, tem_foto INTEGER NOT NULL,
 estado TEXT NOT NULL DEFAULT 'pendente', tentativas INTEGER NOT NULL DEFAULT 0,
 proxima REAL NOT NULL DEFAULT 0, erro TEXT, decisao TEXT, hash TEXT,
 produto_id INTEGER, resultado TEXT, finalizado_em REAL, disponibilizado_em REAL,
 PRIMARY KEY(canal_id,msg_id)
);
CREATE INDEX ix_eventos_elegiveis ON eventos(estado,proxima,origem,recebido_em);
CREATE TABLE donos_hash (hash TEXT PRIMARY KEY, canal_id INTEGER NOT NULL, msg_id INTEGER NOT NULL);
CREATE TABLE midias (
 produto_id INTEGER PRIMARY KEY, canal_id INTEGER NOT NULL, msg_id INTEGER NOT NULL,
 chave TEXT NOT NULL UNIQUE, estado TEXT NOT NULL DEFAULT 'pendente',
 tentativas INTEGER NOT NULL DEFAULT 0, proxima REAL NOT NULL DEFAULT 0,
 erro TEXT, url TEXT, enviado INTEGER NOT NULL DEFAULT 0,
 compensar INTEGER NOT NULL DEFAULT 0, finalizado_em REAL, falha_apos_limpeza TEXT
);
CREATE INDEX ix_midias_elegiveis ON midias(estado,proxima);
CREATE TABLE resolucoes (
 username TEXT PRIMARY KEY, proxima REAL NOT NULL DEFAULT 0,
 tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT
);
PRAGMA user_version=4;
"""


def criar_v4(diretorio: Path) -> dict:
    with sqlite3.connect(diretorio / "inbox.sqlite3") as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA_V4)
        db.execute("""INSERT INTO canais VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (CANAL, "canal", "123456789", '["@Canal", "antigo"]', 7, 123, 90, 456, 3, "FloodWait", 1, 6))
        decisao = '{"titulo": "Produto antigo", "preco": 99.9, "link": "https://loja.test/ABC"}'
        for msg_id, estado in ((8, "processando"), (9, "pendente"), (10, "aprovada")):
            db.execute("""INSERT INTO eventos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (CANAL, msg_id, "antigo", "@Canal", "texto bruto antigo", DATA.isoformat(),
                        100, "historico", 1, estado, 2, 0, "TimeoutError", decisao if msg_id != 9 else None,
                        "hash-congelado" if msg_id != 9 else None, 42 if msg_id == 10 else None,
                        "salva" if msg_id == 10 else None, 200 if msg_id == 10 else None,
                        190 if msg_id == 10 else None))
        db.execute("INSERT INTO donos_hash VALUES(?,?,?)", ("hash-congelado", CANAL, 8))
        db.execute("INSERT INTO midias VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (42, CANAL, 10, "42_foto.jpg", "processando", 3, 0, "TimeoutError",
                    "https://storage.test/foto", 1, 1, None, "ErroPermanente"))
        db.execute("INSERT INTO resolucoes VALUES(?,?,?,?)", ("outro", 999, 2, "FloodWait"))
        return {tabela: [dict(r) for r in db.execute(f"SELECT * FROM {tabela}")]
                for tabela in ("canais", "eventos", "midias", "donos_hash", "resolucoes")}


class TestEnvelope(unittest.TestCase):
    def test_default_independente_posicional_e_subclasse_com_default(self) -> None:
        @dataclass(frozen=True)
        class EntradaSimulada(Mensagem):
            atraso: float = 0

        msg = EntradaSimulada(CANAL, 1, "canal", "original", DATA.isoformat(), True, "live", 123)
        outra = Mensagem(CANAL, 2, "canal", "outro", DATA.isoformat())
        self.assertEqual((msg.recebido_em, msg.atraso, msg.contexto), (123, 0, {}))
        self.assertIsNot(msg.contexto, outra.contexto)

    def test_bruto_vazio_nao_consulta_text_e_fallback_legado(self) -> None:
        class Bruta:
            id, date, message = 1, DATA, ""

            @property
            def text(self):
                raise AssertionError(".text formatado não deve ser consultado")

        self.assertEqual(Telegram.envelope(Bruta(), CANAL, "canal").texto, "")
        for campos, esperado in (({"text": "legado"}, "legado"), ({"message": None, "text": "fake"}, "fake"), ({}, "")):
            with self.subTest(campos=campos):
                msg = SimpleNamespace(id=1, date=DATA, **campos)
                envelope = Telegram.envelope(msg, CANAL, "canal")
                self.assertEqual(envelope.texto, esperado)
                self.assertEqual(envelope.contexto, {"versao": 1, "links": [], "codigos": [], "exclusoes": []})


@unittest.skipUnless(TEM_TELETHON, "Telethon fixado necessário para offsets UTF-16")
class TestContextoTelethon(unittest.IsolatedAsyncioTestCase):
    def mensagem_sdk(self):
        from telethon.tl.types import (KeyboardButtonCallback, KeyboardButtonRow, KeyboardButtonUrl,
            Message, MessageEntityCode, MessageEntityPre, MessageEntityTextUrl, MessageEntityUrl,
            PeerChannel, ReplyInlineMarkup)

        texto = "🚀 SSD R$ 99,90\nComprar 🛒 aqui\nCupom: AbC123\nbloco\nhttps://loja.test/A(B)?Q=X#Z"

        def entidade(tipo, trecho, **campos):
            inicio = texto.index(trecho)
            return tipo(offset=len(texto[:inicio].encode("utf-16-le")) // 2,
                        length=len(trecho.encode("utf-16-le")) // 2, **campos)

        msg = Message(id=8, peer_id=PeerChannel(111), date=DATA, message=texto,
            entities=[entidade(MessageEntityTextUrl, "Comprar 🛒 aqui", url="https://loja.test/Produto?X=A"),
                      entidade(MessageEntityCode, "AbC123"), entidade(MessageEntityPre, "bloco", language=""),
                      entidade(MessageEntityUrl, "https://loja.test/A(B)?Q=X#Z")],
            reply_markup=ReplyInlineMarkup(rows=[KeyboardButtonRow(buttons=[
                KeyboardButtonUrl(text="Comprar agora", url="https://loja.test/Botao?X=Y"),
                KeyboardButtonCallback(text="Não executar", data=b"callback")])]))
        return msg

    async def test_live_e_raw_tipados_mesmo_contexto_utf16_sem_enriquecimento(self) -> None:
        from telethon import utils
        from telethon.tl.types import Message
        from src.avaliacao import avaliar_mensagem
        from src.filters import preparar_filtros
        from tests.test_regressoes_telethon import cliente_historico

        with tempfile.TemporaryDirectory() as tmp:
            estado = EstadoLocal(Path(tmp))
            await estado.abrir()
            try:
                await estado.configurar_canal(CANAL, "canal", 123, DATA.timestamp() - 86400)
                await estado.iniciar_varredura(CANAL, 8)
                cliente = cliente_historico()
                cliente.historico = [self.mensagem_sdk()]
                # .text de Message raw não está inicializado pelo iterador. Nenhum
                # caminho deve depender dele, get_buttons ou parse_mode.unparse.
                with patch.object(Message, "text", new_callable=PropertyMock, side_effect=AssertionError("markup proibido")), \
                     patch.object(Message, "get_buttons", new=AsyncMock(side_effect=AssertionError("RPC proibida"))) as botoes, \
                     patch.object(cliente, "get_entity", new=AsyncMock(side_effect=AssertionError("RPC proibida"))) as resolver, \
                     patch.object(utils, "get_inner_text", wraps=utils.get_inner_text) as inner:
                    live = Telegram.envelope(self.mensagem_sdk(), CANAL, "canal", "live")
                    pagina = await Telegram(cliente, estado).pagina(await estado.canal(CANAL), 100)
                raw = pagina.mensagens[0]
                self.assertEqual((raw.texto, raw.contexto), (live.texto, live.contexto))
                filtros = preparar_filtros([{"palavras_chave": ["ssd"]}])
                extraida_live = avaliar_mensagem(live.texto, filtros, live.contexto)
                self.assertTrue(extraida_live.aceita)
                self.assertEqual(extraida_live, avaliar_mensagem(raw.texto, filtros, raw.contexto))
                self.assertEqual((raw.msg_id, raw.canal_id, raw.origem), (8, CANAL, "historico"))
                self.assertEqual(cliente.requisicoes, [(0, -100, 100)])
                self.assertEqual(pagina.cursor, 8)
                self.assertTrue(pagina.esgotou)
                botoes.assert_not_awaited()
                resolver.assert_not_awaited()
                self.assertEqual(inner.call_count, 2, "Uma conversão SDK de entidades por mensagem")
                contexto = live.contexto
                self.assertEqual(set(contexto), {"versao", "links", "codigos", "exclusoes"})
                self.assertEqual(contexto["versao"], 1)
                spans = lambda trechos: [{"offset": live.texto.index(t), "length": len(t)} for t in trechos]
                links = contexto["links"]
                self.assertEqual(links, [
                    {"url": "https://loja.test/Produto?X=A", "origem": "entidade", "rotulo": "Comprar 🛒 aqui", **spans(["Comprar 🛒 aqui"])[0]},
                    {"url": "https://loja.test/A(B)?Q=X#Z", "origem": "entidade", "rotulo": "https://loja.test/A(B)?Q=X#Z", **spans(["https://loja.test/A(B)?Q=X#Z"])[0]},
                    {"url": "https://loja.test/Botao?X=Y", "origem": "botao", "rotulo": "Comprar agora"}])
                self.assertEqual(contexto["codigos"], spans(["AbC123", "bloco"]))
                self.assertEqual(contexto["exclusoes"], spans(["https://loja.test/A(B)?Q=X#Z"]))
                self.assertNotIn(live.texto, json.dumps(contexto, ensure_ascii=False))
                await estado.registrar(raw)
                await estado.fechar()
                estado = EstadoLocal(Path(tmp))
                await estado.abrir()
                job = await estado.obter_oferta(DATA.timestamp(), True)
                self.assertEqual((job["texto"], json.loads(job["contexto"])), (raw.texto, raw.contexto))
                self.assertEqual(extraida_live, avaliar_mensagem(job["texto"], filtros, json.loads(job["contexto"])))
            finally:
                await estado.fechar()

    async def test_spans_malformados_nao_impedem_entidades_validas(self) -> None:
        from telethon.tl.types import MessageEntityTextUrl

        msg = self.mensagem_sdk()
        validas = list(msg.entities)
        msg.entities = [MessageEntityTextUrl(offset=o, length=n, url="https://invalida.test")
                        for o, n in ((-1, 2), (1, 1), (0, 1), (0, 9999), (0, 0), ("1", 1), (True, 1))] + validas
        envelope = Telegram.envelope(msg, CANAL, "canal")
        self.assertEqual(envelope.contexto, Telegram.envelope(self.mensagem_sdk(), CANAL, "canal").contexto)

    async def test_nome_produto_em_texturl_nao_e_excluido_da_descricao(self) -> None:
        from telethon.tl.types import Message, MessageEntityTextUrl, PeerChannel
        from src.avaliacao import avaliar_mensagem
        from src.filters import preparar_filtros

        texto = "🚀 SSD Kingston NV2 1 TB\nPor R$ 299,90"
        nome = "SSD Kingston NV2 1 TB"
        msg = Message(id=9, peer_id=PeerChannel(111), date=DATA, message=texto,
            entities=[MessageEntityTextUrl(offset=3, length=len(nome), url="https://loja.test/Produto")])
        envelope = Telegram.envelope(msg, CANAL, "canal")
        resultado = avaliar_mensagem(envelope.texto,
            preparar_filtros([{"palavras_chave": ["ssd", "kingston"], "modo_palavras": "todas"}]),
            envelope.contexto)
        self.assertTrue(resultado.aceita)
        self.assertIn(nome, resultado.extracao.produto["titulo"])
        self.assertEqual(resultado.extracao.produto["link"], "https://loja.test/Produto")


class TestContextoSQLite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.diretorio = Path(self.tmp.name)
        self.estado = EstadoLocal(self.diretorio)
        self.addAsyncCleanup(self.fechar)

    async def fechar(self) -> None:
        await self.estado.fechar()

    async def reiniciar(self) -> None:
        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()

    def mensagem(self, **campos) -> Mensagem:
        return replace(Mensagem(CANAL, 1, "canal", "original único", DATA.isoformat()), **campos)

    async def test_migracao_v4_real_preserva_jobs_decisao_hash_midia_aliases_cursor(self) -> None:
        anterior = criar_v4(self.diretorio)
        await self.estado.abrir()
        self.assertEqual(await self.estado.canal(CANAL), anterior["canais"][0])
        self.assertEqual(await self.estado.aliases(CANAL), ["@Canal", "antigo"])
        for antigo in anterior["eventos"]:
            esperado = {**antigo, "contexto": "{}", "diagnostico": "{}"}
            if esperado["estado"] == "processando":
                esperado["estado"] = "retry"
            self.assertEqual(await self.estado.evento(CANAL, antigo["msg_id"]), esperado)
        self.assertEqual(await self.estado.midia(42), {**anterior["midias"][0], "estado": "retry"})
        self.assertEqual(await self.estado.resolucao("outro"), anterior["resolucoes"][0])
        donos = await self.estado._executar(lambda: [dict(r) for r in self.estado.db.execute("SELECT * FROM donos_hash")])
        self.assertEqual(donos, anterior["donos_hash"])
        self.assertEqual(await self.estado._executar(lambda: self.estado.db.execute("PRAGMA user_version").fetchone()[0]), 5)
        job = await self.estado.obter_oferta(1000, True)
        self.assertEqual((job["msg_id"], job["decisao"], job["hash"], job["tentativas"]),
                         (8, anterior["eventos"][0]["decisao"], "hash-congelado", 3))
        self.assertTrue(await self.estado.reservar_hash(job, job["hash"]))
        self.assertEqual((await self.estado.obter_midia(1000))["produto_id"], 42)
        await self.reiniciar()
        self.assertEqual((await self.estado.evento(CANAL, 8))["decisao"], job["decisao"])
        self.assertEqual((await self.estado.evento(CANAL, 10))["estado"], "aprovada")
        self.assertEqual((await self.estado.midia(42))["estado"], "retry")
        self.assertEqual(await self.estado.canal(CANAL), anterior["canais"][0])

    async def test_versoes_0_a_3_aditivas_preservam_registros(self) -> None:
        for versao in range(4):
            with self.subTest(versao=versao), tempfile.TemporaryDirectory() as tmp:
                diretorio = Path(tmp)
                anterior = criar_v4(diretorio)
                with sqlite3.connect(diretorio / "inbox.sqlite3") as db:
                    db.execute("DROP TABLE resolucoes")
                    db.execute("ALTER TABLE canais DROP COLUMN geracao")
                    db.execute("ALTER TABLE eventos DROP COLUMN disponibilizado_em")
                    db.execute("ALTER TABLE midias DROP COLUMN falha_apos_limpeza")
                    db.execute(f"PRAGMA user_version={versao}")
                estado = EstadoLocal(diretorio)
                await estado.abrir()
                try:
                    evento = await estado.evento(CANAL, 10)
                    self.assertEqual(evento["decisao"], anterior["eventos"][2]["decisao"])
                    self.assertEqual(evento["hash"], "hash-congelado")
                    self.assertEqual((evento["contexto"], evento["diagnostico"], evento["disponibilizado_em"]), ("{}", "{}", None))
                    self.assertEqual((await estado.canal(CANAL))["geracao"], 0)
                    self.assertIsNone((await estado.midia(42))["falha_apos_limpeza"])
                finally:
                    await estado.fechar()

    async def test_falha_no_segundo_alter_reverte_colunas_versao_e_claims(self) -> None:
        anterior = criar_v4(self.diretorio)
        conectar = sqlite3.connect

        class ConexaoComFalha(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if "ADD COLUMN diagnostico" in sql:
                    raise sqlite3.OperationalError("falha injetada após adicionar contexto")
                return super().execute(sql, *args, **kwargs)

        with patch("src.estado.sqlite3.connect", side_effect=lambda *a, **k: conectar(*a, **k, factory=ConexaoComFalha)):
            with self.assertRaises(FalhaLocal):
                await self.estado.abrir()
        with conectar(self.diretorio / "inbox.sqlite3") as db:
            db.row_factory = sqlite3.Row
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            colunas = {r[1] for r in db.execute("PRAGMA table_info(eventos)")}
            self.assertNotIn("contexto", colunas)
            self.assertNotIn("diagnostico", colunas)
            for tabela, registros in anterior.items():
                self.assertEqual([dict(r) for r in db.execute(f"SELECT * FROM {tabela}")], registros)
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.assertEqual((await self.estado.evento(CANAL, 8))["estado"], "retry")

    async def test_contexto_diagnostico_decisao_persistem_sem_enriquecer_duplicata(self) -> None:
        await self.estado.abrir()
        contexto = {"versao": 1, "links": [{"url": "https://loja.test/A", "origem": "botao", "rotulo": "Comprar"}],
                    "codigos": [], "exclusoes": []}
        msg = self.mensagem(contexto=contexto)
        self.assertTrue(await self.estado.registrar(msg))
        job = await self.estado.obter_oferta(DATA.timestamp(), True)
        produto = {"titulo": "Produto", "preco": 0, "cupom": None}
        diagnostico = {"versao": 1, "motivos": ["aceita_por_regra"]}
        await self.estado.decidir(job, produto, "hash-original", diagnostico)
        self.assertTrue(await self.estado.reservar_hash(job, "hash-original"))
        await self.reiniciar()
        antes = await self.estado.evento(CANAL, 1)
        self.assertFalse(await self.estado.registrar(self.mensagem(texto="não substituir", contexto={"novo": True})))
        self.assertEqual(await self.estado.evento(CANAL, 1), antes)
        self.assertEqual(json.loads(antes["contexto"]), contexto)
        self.assertEqual(json.loads(antes["decisao"]), produto)
        self.assertEqual(json.loads(antes["diagnostico"]), diagnostico)
        self.assertEqual(antes["hash"], "hash-original")
        # Chamadas antigas sem diagnóstico não apagam o já confirmado.
        await self.estado.decidir(job, produto, "hash-original")
        await self.estado.finalizar_oferta(job, "aprovada", 42, midia=True)
        final = await self.estado.evento(CANAL, 1)
        self.assertEqual(final["diagnostico"], antes["diagnostico"])
        self.assertEqual((final["estado"], final["hash"]), ("aprovada", "hash-original"))
        self.assertIsNotNone(await self.estado.midia(42))
        self.assertFalse(await self.estado.registrar(self.mensagem(contexto={})))
        self.assertEqual(await self.estado.evento(CANAL, 1), final)

    async def test_diagnostico_terminal_e_json_finito_sem_confirmacao_parcial(self) -> None:
        await self.estado.abrir()
        with self.assertRaises(ValueError):
            await self.estado.registrar(self.mensagem(contexto={"numero": float("nan")}))
        self.assertIsNone(await self.estado.evento(CANAL, 1))
        await self.estado.registrar(self.mensagem())
        job = await self.estado.obter_oferta(DATA.timestamp(), True)
        for operacao in (
            lambda: self.estado.decidir(job, {"titulo": "Produto"}, "nao-gravar", {"numero": float("inf")}),
            lambda: self.estado.finalizar_oferta(job, "descartada", diagnostico={"numero": float("nan")}),
        ):
            with self.assertRaises(ValueError):
                await operacao()
            atual = await self.estado.evento(CANAL, 1)
            self.assertIsNone(atual["decisao"])
            self.assertIsNone(atual["hash"])
            self.assertEqual((atual["estado"], atual["diagnostico"]), ("processando", "{}"))
        diagnostico = {"motivos": ["sem_evidencia_de_oferta"]}
        await self.estado.finalizar_oferta(job, "descartada", resultado="sem_produto", diagnostico=diagnostico)
        await self.reiniciar()
        atual = await self.estado.evento(CANAL, 1)
        self.assertEqual((atual["estado"], atual["resultado"]), ("descartada", "sem_produto"))
        self.assertEqual(json.loads(atual["diagnostico"]), diagnostico)
        self.assertIsNone(await self.estado.obter_oferta(DATA.timestamp(), True))

    async def test_pagina_contexto_invalido_reverte_insercao_e_cursor(self) -> None:
        await self.estado.abrir()
        await self.estado.configurar_canal(CANAL, "canal", 123, 0)
        await self.estado.iniciar_varredura(CANAL, 10)
        mensagens = [self.mensagem(origem="historico"), self.mensagem(msg_id=2, origem="historico", contexto={"n": float("nan")})]
        with self.assertRaises(ValueError):
            await self.estado.registrar_pagina(CANAL, mensagens, 2, False, 0)
        self.assertIsNone(await self.estado.evento(CANAL, 1))
        self.assertEqual((await self.estado.canal(CANAL))["cursor"], 0)
