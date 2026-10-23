"""Contrato das versões realmente instaladas; HTTP interceptado, sem serviços reais."""

import asyncio
import importlib.util
import inspect
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.db import criar_cliente, fechar_cliente
from src.estado import EstadoLocal
from src.main import limitar_updates
from src.midia import ArmazenamentoSupabase
from src.modelos import ErroPermanente
from src.modelos import ErroHTTPRemoto
from src.politica import classificar
from src.repository import RepositorioSupabase
from src.telegram import Telegram

SDK = all(importlib.util.find_spec(n) is not None for n in ("supabase", "telethon", "httpx"))


@unittest.skipUnless(SDK, "Instale bot/requirements.txt para contratos dos SDKs (HTTP continua falso)")
class TestSDK(unittest.IsolatedAsyncioTestCase):
    async def test_cliente_real_timeouts_queries_storage_e_fechamento(self) -> None:
        import httpx
        from supabase import AsyncClient

        with patch("httpx.AsyncClient.send", new=AsyncMock(side_effect=AssertionError("Rede real proibida"))):
            cliente = await criar_cliente("https://sdk.invalid", "e30.e30.aA", 2, 7)
        self.assertIsInstance(cliente, AsyncClient)
        self.assertEqual(cliente.postgrest.session.timeout.read, 2)
        self.assertEqual(cliente.storage.session.timeout.read, 7)
        self.assertTrue(inspect.iscoroutinefunction(cliente.storage.from_("produtos").get_public_url))
        chamadas = []
        def responder(request):
            chamadas.append((request.method, request.url.path, str(request.url.query)))
            if request.url.path.endswith("/filtros"):
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/produtos"):
                return httpx.Response(200, json=[{"id": 1, "foto_url": None}])
            if "/object/" in request.url.path:
                return httpx.Response(200, json=[] if request.method == "DELETE" else {"Key": "produtos/1.jpg"})
            raise AssertionError("Chamada não prevista: " + request.url.path)
        await cliente.postgrest.session.aclose()
        await cliente.storage.session.aclose()
        cliente.postgrest.session = httpx.AsyncClient(base_url=cliente.rest_url, transport=httpx.MockTransport(responder))
        storage_http = httpx.AsyncClient(base_url=cliente.storage_url + "/", transport=httpx.MockTransport(responder))
        cliente.storage.session = storage_http
        cliente.storage._client = storage_http
        try:
            repo = RepositorioSupabase(cliente)
            self.assertEqual(await repo.carregar_filtros(), [])
            self.assertEqual((await repo.buscar_produto(1))["id"], 1)
            storage = ArmazenamentoSupabase(cliente)
            url = await storage.enviar("1.jpg", b"jpeg")
            self.assertIn("/object/public/produtos/1.jpg", url)
            await storage.remover("1.jpg")
            self.assertEqual(len(chamadas), 4)
        finally:
            await fechar_cliente(cliente)
        self.assertTrue(cliente.postgrest.session.is_closed)
        self.assertTrue(storage_http.is_closed)

    async def test_cliente_telethon_fixado_sem_conexao_e_fila_limitada(self) -> None:
        import telethon
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        self.assertEqual(telethon.__version__, "1.36.0")
        cliente = TelegramClient(StringSession(), 12345, "fake", sequential_updates=True,
                                 flood_sleep_threshold=0, request_retries=0, raise_last_call_error=True)
        limitar_updates(cliente, 3, asyncio.Event())
        self.assertIs(cliente._sender._updates_queue, cliente._updates_queue)
        self.assertEqual(cliente._updates_queue.maxsize, 3)
        self.assertFalse(cliente.is_connected())

    async def test_sdk_429_preserva_retry_after_e_400_permanente(self) -> None:
        import httpx
        from types import SimpleNamespace

        for status, codigo in ((429, None), (400, "22P02"), (400, "PGRST204"), (400, None)):
            async with httpx.AsyncClient(base_url="https://sdk.invalid/", transport=httpx.MockTransport(
                lambda request: httpx.Response(status, headers={"Retry-After": "120"},
                    json={"message": "token_nao_logar", "code": codigo}))) as http:
                from postgrest import AsyncPostgrestClient
                from storage3 import AsyncStorageClient
                pg = AsyncPostgrestClient("https://sdk.invalid/")
                storage = AsyncStorageClient("https://sdk.invalid/", {})
                await pg.session.aclose()
                await storage.session.aclose()
                pg.session = http
                storage.session = http
                storage._client = http
                cliente = SimpleNamespace(postgrest=pg, table=pg.table, storage=storage)
                repo = RepositorioSupabase(cliente)
                midia = ArmazenamentoSupabase(cliente)
                for operacao in (repo.carregar_filtros, lambda: midia.enviar("1.jpg", b"foto")):
                    with self.assertRaises(ErroHTTPRemoto) as capturado:
                        await operacao()
                    falha = classificar(capturado.exception, 1, 1, 10)
                    if status == 429:
                        self.assertGreaterEqual(falha.espera, 120)
                        self.assertFalse(falha.permanente)
                    elif codigo == "22P02":
                        self.assertTrue(falha.permanente)
                    else:
                        self.assertFalse(falha.permanente, "Configuração/schema ou 400 desconhecido precisa continuar recuperável")

    async def test_peer_persistido_e_teto_durante_download(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            await estado.configurar_canal(-1000000000111, "canal", 987654321, time.time() - 86400)
            await estado.fechar()
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            blocos = 0
            async def download(*args, **kwargs):
                nonlocal blocos
                for _ in range(20):
                    blocos += 1
                    yield b"12345678"
            cliente = SimpleNamespace(get_messages=AsyncMock(return_value=SimpleNamespace(
                photo=SimpleNamespace(sizes=[]), media="foto")), iter_download=download)
            tg = Telegram(cliente, estado)
            try:
                peer = await tg._peer(-1000000000111)
                self.assertEqual(peer.channel_id, 111)
                self.assertEqual(peer.access_hash, 987654321)
                with self.assertRaises(ErroPermanente):
                    await tg.baixar_foto(-1000000000111, 5, 10)
                self.assertEqual(blocos, 2)
                cliente.get_messages.return_value = None
                with self.assertRaises(ErroPermanente):
                    await tg.baixar_foto(-1000000000111, 5, 10)
            finally:
                await estado.fechar()

    async def test_iterador_tem_bounds_exclusivos_sem_limite_total_50(self) -> None:
        from telethon.tl.functions.messages import GetHistoryRequest
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            await estado.configurar_canal(-1000000000111, "canal", 123, time.time() - 86400)
            pedidos = []

            class ClienteHistoricoFake:
                async def __call__(self, pedido):
                    self_tipo = type(pedido)
                    if self_tipo is not GetHistoryRequest:
                        raise AssertionError("Somente RPC pública de histórico é permitida")
                    pedidos.append(pedido)
                    ids = [n for n in (12, 14, 18) if n >= pedido.offset_id][:pedido.limit]
                    return SimpleNamespace(messages=[SimpleNamespace(id=n, message="mensagem",
                        date=datetime.now(timezone.utc), photo=None) for n in reversed(ids)])

            tg = Telegram(ClienteHistoricoFake(), estado)
            try:
                canal = {**await estado.canal(-1000000000111), "cursor": 10, "limite": 20}
                pagina = await tg.pagina(canal, 100)
                mensagens, esgotou = pagina
                self.assertFalse(esgotou, "Página curta não comprova o restante do intervalo")
                self.assertEqual([m.msg_id for m in mensagens], [12, 14, 18])
                self.assertEqual(pagina.cursor, 18)
                self.assertEqual(len(pedidos), 1, "Uma página não pode esconder outros RPCs")
                vazia = await tg.pagina({**canal, "cursor": pagina.cursor}, 100)
                self.assertTrue(vazia.esgotou)
                self.assertEqual(vazia.cursor, 20)
                self.assertEqual([p.offset_id for p in pedidos], [11, 19])
                self.assertTrue(all(p.limit == 100 and p.add_offset == -100 for p in pedidos))
                self.assertTrue(all(p.min_id == 0 and p.max_id == 0 for p in pedidos),
                                "Bounds são aplicados localmente para evitar a fronteira defeituosa do SDK/API")
            finally:
                await estado.fechar()

    async def test_historico_preserva_entidade_de_codigo_usada_no_cupom(self) -> None:
        from telethon.tl.types import Message, MessageEntityCode, PeerChannel
        from src.extractor import extrair_produto
        from tests.test_regressoes_telethon import CANAL_ID, DATA, cliente_historico

        texto = "Notebook R$ 99,90\nABC12345\nhttps://loja.test/oferta"
        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            try:
                await estado.configurar_canal(CANAL_ID, "canal", 1, DATA.timestamp() - 86400)
                cliente = cliente_historico()
                cliente.historico = [Message(id=12, peer_id=PeerChannel(111), date=DATA,
                    message=texto, entities=[MessageEntityCode(offset=texto.index("ABC12345"), length=8)])]
                canal = {**await estado.canal(CANAL_ID), "limite": 12}
                mensagens, _ = await Telegram(cliente, estado).pagina(canal, 100)
                self.assertEqual(len(mensagens), 1)
                self.assertIn("`ABC12345`", mensagens[0].texto,
                              "Paginação deve manter a mesma formatação .text do caminho ativo")
                produto = await extrair_produto(mensagens[0].texto)
                self.assertEqual(produto["cupom"], "ABC12345")
            finally:
                await estado.fechar()
