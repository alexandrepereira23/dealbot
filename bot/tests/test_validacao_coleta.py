"""Evidências de validação: três defeitos de coleta ainda sem correção.

Os testes exprimem o comportamento seguro esperado, não o comportamento atual.
Não usam credenciais, rede ou estado persistente do serviço.
"""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.config import Config
from src.estado import EstadoLocal
from src.modelos import Mensagem
from src.recuperacao import Recuperacao
from src.telegram import Telegram
from tests.test_regressoes_telethon import CANAL_ID, DATA, TEM_TELETHON, cliente_historico


class TestValidacaoColeta(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.diretorio = Path(self.tmp.name)
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.addAsyncCleanup(self.fechar_estado)

    async def fechar_estado(self) -> None:
        # A referência pode mudar no teste que simula reinício do processo.
        await self.estado.fechar()

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; iterador real necessário")
    async def test_pagina_curta_nao_confirma_cobertura_de_mensagens_ausentes(self) -> None:
        """RF-005: resposta curta não autoriza saltar os IDs 51 a 137."""
        await self.estado.configurar_canal(CANAL_ID, "canal", 1, DATA.timestamp() - 86400)
        await self.estado.iniciar_varredura(CANAL_ID, 137)
        base = type(cliente_historico())

        class ClientePaginaCurta(base):
            async def __call__(self, request, *args, **kwargs):
                resposta = await super().__call__(request, *args, **kwargs)
                if len(self.requisicoes) == 1:
                    # Somente a primeira resposta é curta; os 137 itens continuam
                    # disponíveis no transporte falso e o iterador é o SDK real.
                    resposta.messages = resposta.messages[-50:]
                return resposta

        cliente = ClientePaginaCurta()
        recuperacao = Recuperacao(self.estado, SimpleNamespace(),
            Telegram(cliente, self.estado), Config(), asyncio.Event())
        await recuperacao.rodada()
        canal = await self.estado.canal(CANAL_ID)
        ausentes_confirmados = [msg_id for msg_id in range(1, canal["cursor"] + 1)
            if await self.estado.evento(CANAL_ID, msg_id) is None]
        self.assertEqual(ausentes_confirmados, [],
            "A fronteira confirmou mensagens não persistidas após resposta curta")

        # Uma correção conservadora pode exigir outra rodada; deve continuar do
        # cursor seguro e finalmente persistir todos os eventos, sem salto.
        for _ in range(4):
            await self.estado.acordar_canais()
            await recuperacao.rodada()
        ausentes = [msg_id for msg_id in range(1, 138)
            if await self.estado.evento(CANAL_ID, msg_id) is None]
        self.assertEqual(ausentes, [])
        self.assertEqual((await self.estado.canal(CANAL_ID))["cursor"], 137)

    async def test_desativacao_impede_iniciar_pagina_de_snapshot_antigo(self) -> None:
        """RF-006: B sai da configuração enquanto a página de A está bloqueada."""
        ids = {"a": -1000000000222, "b": CANAL_ID}
        iniciou_a = asyncio.Event()
        liberar_a = asyncio.Event()
        paginas_iniciadas = []

        async def resolver(nome: str) -> dict:
            return {"canal_id": ids[nome], "access_hash": 1, "username": nome}

        async def pagina(canal: dict, quantidade: int) -> tuple[list[Mensagem], bool]:
            paginas_iniciadas.append(canal["username"])
            if canal["username"] == "a":
                iniciou_a.set()
                await liberar_a.wait()
            return [Mensagem(canal["canal_id"], 1, canal["username"], "teste",
                DATA.isoformat(), origem="historico")], True

        repositorio = SimpleNamespace(listar_canais=AsyncMock(return_value=["a", "b"]))
        telegram = SimpleNamespace(resolver=resolver,
            mais_nova=AsyncMock(return_value=1), pagina=pagina)
        recuperacao = Recuperacao(self.estado, repositorio, telegram, Config(), asyncio.Event())
        await recuperacao.atualizar_canais()
        rodada = asyncio.create_task(recuperacao.rodada())
        try:
            await asyncio.wait_for(iniciou_a.wait(), 5)
            self.assertEqual(paginas_iniciadas, ["a"])
            repositorio.listar_canais.return_value = ["a"]
            await recuperacao.atualizar_canais()
            self.assertNotIn(ids["b"], recuperacao.ativos)
            self.assertFalse((await self.estado.canal(ids["b"]))["ativo"])
            liberar_a.set()
            await asyncio.wait_for(rodada, 5)

            evento_b = await self.estado.evento(ids["b"], 1)
            self.assertEqual((paginas_iniciadas, evento_b), (["a"], None),
                "Canal já desativado não pode iniciar página nem aceitar outro evento")
        finally:
            liberar_a.set()
            if not rodada.done():
                rodada.cancel()
            await asyncio.gather(rodada, return_exceptions=True)

    async def test_floodwait_de_resolucao_sobrevive_ao_reinicio_do_mesmo_estado(self) -> None:
        """RF-003: reinício não encurta a espera mínima por endereço não resolvido."""
        class FloodWait(Exception):
            seconds = 120

        repositorio = SimpleNamespace(listar_canais=AsyncMock(return_value=["canal"]))
        telegram = SimpleNamespace(resolver=AsyncMock(side_effect=FloodWait()))
        recuperacao = Recuperacao(self.estado, repositorio, telegram, Config(), asyncio.Event())
        inicio = time.monotonic()
        await recuperacao.atualizar_canais()
        self.assertEqual(telegram.resolver.await_count, 1)

        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        recuperacao = Recuperacao(self.estado, repositorio, telegram, Config(), asyncio.Event())
        self.assertLess(time.monotonic() - inicio, 120,
            "A reprodução precisa reiniciar antes de vencer o FloodWait")
        await recuperacao.atualizar_canais()
        self.assertEqual(telegram.resolver.await_count, 1,
            "Reabrir o mesmo SQLite deve preservar o FloodWait de 120 segundos")
