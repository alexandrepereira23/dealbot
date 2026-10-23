"""Cobertura histórica, refresh e fronteiras com clientes Telegram falsos."""

import asyncio
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.config import Config
from src.estado import EstadoLocal
from src.main import FilaUpdatesLimitada, limitar_updates, supervisionar_conexao
from src.modelos import Mensagem
from src.recuperacao import Recuperacao
from src.telegram import Telegram


class HistoricoFake:
    def __init__(self) -> None:
        self.enderecos = {"canal": -100111, "outro": -100222, "renomeado": -100111}
        self.mensagens = {}
        self.limite = None
        self.cortado = None

    async def resolver(self, username: str) -> dict:
        if username not in self.enderecos:
            raise ValueError("canal_inacessivel")
        return {"canal_id": self.enderecos[username], "access_hash": 123, "username": username}

    async def mais_nova(self, canal_id: int) -> int:
        return self.limite if self.limite is not None else max((m.msg_id for m in self.mensagens.get(canal_id, [])), default=0)

    async def pagina(self, canal: dict, quantidade: int) -> tuple[list[Mensagem], bool]:
        self.cortado = canal["bootstrap"]
        msgs = [m for m in self.mensagens.get(canal["canal_id"], []) if canal["cursor"] < m.msg_id <= canal["limite"]]
        # Retorna página curta sem prometer exaustão: próxima rodada tem de continuar.
        tamanho = min(quantidade, 17)
        return msgs[:tamanho], len(msgs) < tamanho


class TestRecuperacao(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        self.repo = SimpleNamespace(listar_canais=AsyncMock(return_value=["@CANAL"]))
        self.tg = HistoricoFake()
        self.cfg = replace(Config(), recuperacao_pausa=0.001)
        self.rec = Recuperacao(self.estado, self.repo, self.tg, self.cfg, asyncio.Event())
        await self.rec.atualizar_canais()

    async def asyncTearDown(self) -> None:
        await self.estado.fechar()
        self.tmp.cleanup()

    async def test_137_mensagens_com_lacunas_live_alto_e_reinicio_no_meio(self) -> None:
        msgs = [Mensagem(-100111, 3 * n, "canal", "texto", "2026-10-22T12:00:00+00:00", origem="historico")
                for n in range(1, 138)]
        self.tg.mensagens[-100111] = msgs
        self.tg.limite = 500  # Mensagem superior apagada, não há IDs consecutivos.
        await self.estado.registrar(Mensagem(-100111, 1000, "canal", "live", "2026-10-22T12:00:00+00:00"))
        await self.rec.rodada()
        self.assertEqual((await self.estado.canal(-100111))["cursor"], 51)
        await self.estado.fechar()
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        self.rec = Recuperacao(self.estado, self.repo, self.tg, self.cfg, asyncio.Event())
        for _ in range(12):
            await asyncio.sleep(0.002)
            await self.rec.rodada()
        canal = await self.estado.canal(-100111)
        self.assertEqual(canal["cursor"], 500)
        self.assertIsNone(canal["limite"])
        for msg in msgs:
            self.assertIsNotNone(await self.estado.evento(-100111, msg.msg_id))
        self.assertEqual((await self.estado.resumo())["ofertas"]["pendente"], 138)

    async def test_pagina_toda_duplicada_avanca_cobertura_sem_refazer_evento(self) -> None:
        msgs = [Mensagem(-100111, n, "canal", "texto", "2026-10-22T12:00:00+00:00", origem="historico") for n in range(1, 10)]
        for msg in msgs:
            await self.estado.registrar(msg)
        self.tg.mensagens[-100111] = msgs
        await self.rec.rodada()
        self.assertEqual((await self.estado.canal(-100111))["cursor"], 9)
        self.assertEqual((await self.estado.resumo())["ofertas"]["pendente"], 9)

    async def test_bootstrap_vazio_fixo_e_reativacao_preserva_marcador(self) -> None:
        inicial = (await self.estado.canal(-100111))["bootstrap"]
        await self.rec.rodada()
        self.assertEqual(self.tg.cortado, inicial)
        self.repo.listar_canais.return_value = []
        await self.rec.atualizar_canais()
        self.assertFalse((await self.estado.canal(-100111))["ativo"])
        self.repo.listar_canais.return_value = ["renomeado"]
        await self.rec.atualizar_canais()
        canal = await self.estado.canal(-100111)
        self.assertTrue(canal["ativo"])
        self.assertEqual(canal["bootstrap"], inicial)
        self.assertIn("renomeado", await self.estado.aliases(-100111))
        self.assertIn("canal", await self.estado.aliases(-100111))

    async def test_atualizacao_canais_individual_e_erro_global_preserva_lista(self) -> None:
        self.repo.listar_canais.return_value = ["canal", "outro", "quebrado"]
        await self.rec.atualizar_canais()
        self.assertEqual(set(self.rec.ativos), {-100111, -100222})
        self.repo.listar_canais.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await self.rec.atualizar_canais()
        self.assertEqual(set(self.rec.ativos), {-100111, -100222})
        self.repo.listar_canais.side_effect = None
        self.repo.listar_canais.return_value = []
        await self.rec.atualizar_canais()
        self.assertEqual(self.rec.ativos, {})
        self.repo.listar_canais.return_value = ["canal"]
        await self.rec.atualizar_canais()
        self.assertEqual(set(self.rec.ativos), {-100111})

    async def test_preserva_grafias_configurada_e_canonica_como_aliases(self) -> None:
        self.repo.listar_canais.return_value = ["@Canal"]
        self.tg.resolver = AsyncMock(return_value={"canal_id": -100111, "username": "CaNaL", "access_hash": 123})
        await self.rec.atualizar_canais()
        aliases = await self.estado.aliases(-100111)
        self.assertIn("@Canal", aliases)
        self.assertIn("CaNaL", aliases)

    async def test_limite_servidor_aguarda_sem_avancar_cursor(self) -> None:
        class FloodWait(Exception):
            seconds = 120
        self.tg.mais_nova = AsyncMock(side_effect=FloodWait())
        await self.rec.rodada()
        canal = await self.estado.canal(-100111)
        self.assertEqual(canal["cursor"], 0)
        self.assertGreater(canal["proxima"], time.time() + 119)
        await self.estado.acordar_canais()
        await self.rec.rodada()
        self.assertEqual(self.tg.mais_nova.await_count, 1)

    async def test_reconexao_por_rpc_dispara_historico_com_logica_conectada(self) -> None:
        class Saudavel:
            client = SimpleNamespace(is_connected=lambda: True)
            saudavel = AsyncMock(side_effect=[TimeoutError(), True, True, True])
        cfg = replace(self.cfg, retry_base=0.001, retry_max=0.001, recuperacao_intervalo=0.01)
        with unittest.mock.patch.object(self.estado, "acordar_canais", new=AsyncMock()) as acordar:
            tarefa = asyncio.create_task(supervisionar_conexao(Saudavel(), self.rec, asyncio.Event(), cfg))
            try:
                await asyncio.wait_for(self.rec.acordar.wait(), 1)
                await asyncio.sleep(0.025)
                acordar.assert_awaited_once()
            finally:
                tarefa.cancel()
                await asyncio.gather(tarefa, return_exceptions=True)


class TestTransporte(unittest.IsolatedAsyncioTestCase):
    async def test_envelope_preserva_precedencia_do_texto_formatado_original(self) -> None:
        from datetime import datetime, timezone
        msg = SimpleNamespace(id=1, date=datetime.now(timezone.utc), photo=None,
            text="Notebook R$ 99,90 `CUPOM123`", message="Notebook R$ 99,90 CUPOM123")
        envelope = Telegram.envelope(msg, -100111, "canal", "live")
        self.assertEqual(envelope.texto, msg.text)

    async def test_fila_overflow_e_limites_reais_instalados_em_cliente_fake(self) -> None:
        evento = asyncio.Event()
        cliente = SimpleNamespace(_updates_queue=asyncio.Queue(), _sender=SimpleNamespace(_updates_queue=asyncio.Queue()))
        limitar_updates(cliente, 2, evento)
        self.assertIs(cliente._updates_queue, cliente._sender._updates_queue)
        for n in range(100):
            cliente._updates_queue.put_nowait(n)
        self.assertEqual(cliente._updates_queue.qsize(), 2)
        self.assertTrue(evento.is_set())
        self.assertEqual(cliente._updates_queue.get_nowait(), 0)
