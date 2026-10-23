"""Regressões offline da versão fixada: transporte falso, iterador real."""

import asyncio
import importlib.util
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.config import Config
from src.estado import EstadoLocal
from src.main import servir
from src.modelos import ErroPermanente
from src.pipeline import Pipeline
from src.recuperacao import Recuperacao
from src.telegram import Telegram


TEM_TELETHON = importlib.util.find_spec("telethon") is not None
CANAL_ID = -1000000000111
DATA = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def cliente_historico():
    """Somente GetHistory é permitido; connect e RPC de rede sempre falham."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl import functions, types

    class ClienteHistorico(TelegramClient):
        def __init__(self):
            super().__init__(StringSession(), 123, "hash-falso")
            self.requisicoes = []
            self.historico = [types.Message(id=i, peer_id=types.PeerChannel(111),
                date=DATA, message=f"Notebook de teste {i} R$ 99,90")
                for i in range(1, 138)]

        async def connect(self, *args, **kwargs):
            raise AssertionError("O teste não pode abrir conexão Telegram")

        async def _call(self, *args, **kwargs):
            raise AssertionError("O teste não pode executar RPC de rede")

        async def get_input_entity(self, peer):
            if not isinstance(peer, types.InputPeerChannel):
                raise AssertionError("Peer inesperado no transporte falso")
            return peer

        async def __call__(self, request, *args, **kwargs):
            if not isinstance(request, functions.messages.GetHistoryRequest):
                raise AssertionError("Somente GetHistory falso é permitido")
            self.requisicoes.append((request.offset_id, request.add_offset, request.limit))
            # GetHistory devolve ordem decrescente. add_offset negativo seleciona
            # a janela seguinte ao offset, usada pelo reverse=True do SDK real.
            if request.add_offset < 0:
                inicio = max(1, request.offset_id)
                mensagens = [m for m in self.historico if m.id >= inicio][:request.limit]
                mensagens = list(reversed(mensagens))
            else:
                mensagens = [m for m in reversed(self.historico)
                    if not request.offset_id or m.id < request.offset_id][:request.limit]
            return SimpleNamespace(messages=mensagens, users=[], chats=[], count=137)

    return ClienteHistorico()


@unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; teste do iterador real ignorado")
class TestHistoricoTelethonReal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.estado = EstadoLocal(Path(self.tmp.name))
        await self.estado.abrir()
        self.addAsyncCleanup(self.estado.fechar)
        await self.estado.configurar_canal(CANAL_ID, "canal", 1, DATA.timestamp() - 86400)
        await self.estado.iniciar_varredura(CANAL_ID, 137)
        self.client = cliente_historico()
        self.telegram = Telegram(self.client, self.estado)

    async def test_sdk_136_reproduz_falsa_exaustao_apos_primeiros_100(self):
        from telethon import __version__

        if __version__ != "1.36.0":
            self.skipTest("Reprodução específica do Telethon 1.36.0 fixado no projeto")
        peer = await self.telegram._peer(CANAL_ID)
        iterador = self.client.iter_messages(peer, min_id=0, max_id=138,
            reverse=True, offset_date=datetime.fromtimestamp(DATA.timestamp() - 86400,
                timezone.utc), limit=None, wait_time=0)
        ids = [m.id async for m in iterador]
        self.assertEqual(ids, list(range(1, 101)))
        self.assertEqual(len(self.client.historico), 137)
        self.assertEqual(self.client.requisicoes, [(0, -100, 100)])

    async def test_lote_200_nao_avanca_cursor_sobre_37_mensagens_nao_coletadas(self):
        config = replace(Config(), buffer_max=200, recuperacao_lote=200)
        canal = await self.estado.canal(CANAL_ID)
        mensagens, esgotou = await self.telegram.pagina(canal, config.recuperacao_lote)
        self.assertEqual([m.msg_id for m in mensagens], list(range(1, 101)))
        self.assertFalse(esgotou, "O orçamento de 100 não comprova exaustão do histórico")
        await self.estado.registrar_pagina(CANAL_ID, mensagens, mensagens[-1].msg_id,
            esgotou, 0)
        parcial = await self.estado.canal(CANAL_ID)
        self.assertEqual(parcial["cursor"], 100)
        self.assertEqual(parcial["limite"], 137)
        self.assertIsNone(await self.estado.evento(CANAL_ID, 101))

        recuperacao = Recuperacao(self.estado, SimpleNamespace(), self.telegram,
            config, asyncio.Event())
        self.assertEqual(await recuperacao.rodada(), 37)
        final = await self.estado.canal(CANAL_ID)
        self.assertEqual(final["cursor"], 137)
        self.assertIsNone(final["limite"])
        for msg_id in range(1, 138):
            with self.subTest(msg_id=msg_id):
                self.assertIsNotNone(await self.estado.evento(CANAL_ID, msg_id))
        self.assertEqual((await self.estado.resumo())["ofertas"], {"pendente": 137})


class IteradorMidiaFake:
    def __init__(self, bloquear=False):
        self.bloquear = bloquear
        self.iniciou = asyncio.Event()
        self.fechamentos = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.iniciou.set()
        if self.bloquear:
            await asyncio.Event().wait()
        return b"foto"

    async def close(self):
        self.fechamentos += 1


class TestFechamentoMidia(unittest.IsolatedAsyncioTestCase):
    def gateway(self, iterador):
        msg = SimpleNamespace(photo=SimpleNamespace(sizes=[]), media=object())
        client = SimpleNamespace(get_messages=AsyncMock(return_value=msg),
            iter_download=Mock(return_value=iterador))
        gateway = Telegram(client, SimpleNamespace())
        gateway._peer = AsyncMock(return_value="peer-falso")
        return gateway

    async def test_limite_durante_download_fecha_iterador(self):
        iterador = IteradorMidiaFake()
        gateway = self.gateway(iterador)
        with self.assertRaisesRegex(ErroPermanente, "midia_excede_limite"):
            await gateway.baixar_foto(CANAL_ID, 1, 3)
        self.assertEqual(iterador.fechamentos, 1)

    async def test_cancelamento_durante_download_fecha_iterador(self):
        iterador = IteradorMidiaFake(bloquear=True)
        gateway = self.gateway(iterador)
        tarefa = asyncio.create_task(gateway.baixar_foto(CANAL_ID, 1, 100))
        try:
            await asyncio.wait_for(iterador.iniciou.wait(), 1)
            tarefa.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await tarefa
            self.assertEqual(iterador.fechamentos, 1)
        finally:
            tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)

    async def test_gerador_assincrono_tem_aclose_no_limite(self):
        fechado = asyncio.Event()

        async def blocos():
            try:
                yield b"foto"
            finally:
                fechado.set()

        iterador = blocos()
        gateway = self.gateway(iterador)
        try:
            with self.assertRaisesRegex(ErroPermanente, "midia_excede_limite"):
                await gateway.baixar_foto(CANAL_ID, 1, 3)
            self.assertTrue(fechado.is_set(), "aclose precisa executar antes do retorno")
        finally:
            await iterador.aclose()


@unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; servir importa events")
class TestEncerramentoComFalhaDisconnect(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_com_erro_ainda_encerra_workers_reais(self):
        with tempfile.TemporaryDirectory() as tmp:
            estado = EstadoLocal(Path(tmp))
            await estado.abrir()
            pipelines = []
            config = replace(Config(), shutdown_timeout=0.05)
            client = SimpleNamespace(add_event_handler=Mock(), remove_event_handler=Mock(),
                connect=AsyncMock(), is_user_authorized=AsyncMock(return_value=False),
                disconnect=AsyncMock(side_effect=ConnectionError("disconnect-falso")))
            parar = asyncio.Event()

            def criar_pipeline(*args, **kwargs):
                pipeline = Pipeline(*args, **kwargs)
                pipeline.encerrar = AsyncMock(wraps=pipeline.encerrar)
                pipelines.append(pipeline)
                return pipeline

            try:
                with patch("src.main.Pipeline", side_effect=criar_pipeline):
                    with self.assertRaisesRegex(ConnectionError, "disconnect-falso"):
                        await servir(client, estado, SimpleNamespace(), SimpleNamespace(),
                            config, parar, asyncio.Event())
                self.assertTrue(parar.is_set())
                client.remove_event_handler.assert_called_once()
                client.disconnect.assert_awaited_once()
                self.assertEqual(len(pipelines), 1)
                pipelines[0].encerrar.assert_awaited_once()
                self.assertEqual(len(pipelines[0].tasks), config.oferta_workers + config.midia_workers)
                self.assertTrue(all(t.done() for t in pipelines[0].tasks))
            finally:
                for pipeline in pipelines:
                    if any(not t.done() for t in pipeline.tasks):
                        await pipeline.encerrar()
                await estado.fechar()


if __name__ == "__main__":
    unittest.main()
