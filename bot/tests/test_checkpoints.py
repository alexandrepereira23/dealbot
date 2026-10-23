"""Regressões das fronteiras remotas: efeito confirmado, retry e retenção."""

import asyncio
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.modelos import ErroHTTPRemoto
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, aguardar, mensagem
from tests.test_repository import ClienteFake


class TestCheckpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self.tmp.name)
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        await self.estado.configurar_canal(-100111, "Canal", 123, time.time() - 86400)
        self.cliente = ClienteFake()
        self.repo = RepositorioSupabase(self.cliente)
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.storage = StorageFake()
        self.config = replace(Config(), oferta_workers=1, retry_base=.01,
                              retry_max=.02, shutdown_timeout=.02)
        self.pipeline = Pipeline(self.estado, self.repo, self.storage,
                                 TelegramFake(), self.cache, self.config)

    async def asyncTearDown(self) -> None:
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def _conferir_admissao_live_tardia(self, reativar: bool) -> None:
        # Esta mensagem já foi aceita e deve continuar processável após desativar.
        await self.estado.registrar(mensagem(10))
        iniciou, liberar = asyncio.Event(), asyncio.Event()
        registrar = self.estado.registrar

        async def registrar_depois(*args, **kwargs):
            iniciou.set()
            await liberar.wait()
            return await registrar(*args, **kwargs)

        with patch.object(self.estado, "registrar", side_effect=registrar_depois):
            tarefa = asyncio.create_task(self.pipeline.receber(mensagem(1)))
            try:
                await asyncio.wait_for(iniciou.wait(), 3)
                await self.estado.ativar_canais([])
                if reativar:
                    await self.estado.ativar_canais([-100111])
                self.assertIsNone(await self.estado.evento(-100111, 1),
                                  "A nova mensagem ainda não foi aceita duravelmente")
                liberar.set()
                self.assertFalse(await asyncio.wait_for(tarefa, 3))
            finally:
                liberar.set()
                await asyncio.gather(tarefa, return_exceptions=True)

        self.assertIsNone(await self.estado.evento(-100111, 1))
        self.pipeline.iniciar()

        async def aceito_concluido() -> bool:
            return bool((await self.estado.evento(-100111, 10))["finalizado_em"])

        await aguardar(aceito_concluido)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(self.cliente.tabelas["produtos"][0]["telegram_msg_id"], 10)

    async def test_live_nao_commitado_rejeitado_apos_desativacao(self) -> None:
        await self._conferir_admissao_live_tardia(reativar=False)

    async def test_live_de_geracao_antiga_rejeitado_apos_desativar_reativar(self) -> None:
        await self._conferir_admissao_live_tardia(reativar=True)

    async def test_falha_permanente_pos_upload_preserva_compensacao_e_retencao(self) -> None:
        self.repo.vincular_foto = AsyncMock(side_effect=ErroHTTPRemoto(422, .01))
        iniciou = asyncio.Event()
        liberar = asyncio.Event()
        remover = self.storage.remover

        async def remover_depois(chave: str) -> None:
            iniciou.set()
            await liberar.wait()
            await remover(chave)

        self.storage.remover = remover_depois
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))

        async def estabilizou() -> bool:
            midia = await self.estado.midia(1)
            return iniciou.is_set() or bool(midia and midia["estado"] == "falha_permanente")

        await aguardar(estabilizou)
        self.assertEqual(len(self.storage.objetos), 1)
        await self.estado.limpar(time.time() + 1)
        self.assertIsNotNone(await self.estado.evento(-100111, 1),
                             "Retenção não pode apagar evento com objeto conhecido ainda sem compensação")
        self.assertIsNotNone(await self.estado.midia(1), "Chave de compensação precisa continuar durável")
        self.assertTrue(iniciou.is_set(), "Falha pós-upload precisa reconciliar/compensar antes de terminalizar")
        liberar.set()

        async def finalizou() -> bool:
            midia = await self.estado.midia(1)
            return midia["estado"] == "falha_permanente" and not midia["compensar"]

        await aguardar(finalizou)
        self.assertEqual(self.storage.objetos, {})
        self.assertEqual(len(self.storage.removidos), 1)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_falha_apos_commit_da_foto_reconcilia_sem_apagar_foto_valida(self) -> None:
        vincular = self.repo.vincular_foto

        async def vincular_e_falhar(produto_id: int, url: str) -> str:
            await vincular(produto_id, url)
            raise ErroHTTPRemoto(422, .01)

        self.repo.vincular_foto = vincular_e_falhar
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))

        async def finalizou() -> bool:
            midia = await self.estado.midia(1)
            return bool(midia and midia["finalizado_em"])

        await aguardar(finalizou)
        self.assertEqual((await self.estado.midia(1))["estado"], "pronta")
        self.assertTrue(self.cliente.tabelas["produtos"][0]["foto_url"])
        self.assertEqual(len(self.storage.objetos), 1)
        self.assertEqual(self.storage.removidos, [])

    async def test_compensacao_pos_upload_sobrevive_a_encerramento_e_reinicio(self) -> None:
        self.repo.vincular_foto = AsyncMock(side_effect=ErroHTTPRemoto(422, .01))
        iniciou = asyncio.Event()
        remover = self.storage.remover

        async def bloquear_remocao(chave: str) -> None:
            iniciou.set()
            await asyncio.Event().wait()

        self.storage.remover = bloquear_remocao
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))
        await asyncio.wait_for(iniciou.wait(), 3)
        await self.pipeline.encerrar()
        pendente = await self.estado.midia(1)
        self.assertTrue(pendente["compensar"])
        self.assertEqual(pendente["falha_apos_limpeza"], "ErroHTTPRemoto:422")
        await self.estado.fechar()

        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.storage.remover = remover
        telegram = TelegramFake()
        self.pipeline = Pipeline(self.estado, self.repo, self.storage,
                                 telegram, self.cache, self.config)
        self.pipeline.iniciar()

        async def finalizou() -> bool:
            midia = await self.estado.midia(1)
            return bool(midia["finalizado_em"])

        await aguardar(finalizou)
        final = await self.estado.midia(1)
        self.assertEqual(final["estado"], "falha_permanente")
        self.assertFalse(final["compensar"])
        self.assertEqual(self.storage.objetos, {})
        self.assertEqual(len(self.storage.removidos), 1)
        self.assertEqual(telegram.chamadas, 0, "Retomada deve compensar o upload, não refazer mídia")
        self.assertEqual(self.repo.vincular_foto.await_count, 1)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_duplicata_preserva_classificacao_apos_falha_de_aparicao_e_reinicio(self) -> None:
        await self.repo.salvar_oferta({"titulo": "Notebook", "preco": 99.9,
            "link": "https://loja.test/1", "canal_origem": "outro", "telegram_msg_id": 900,
            "foto_url": None}, [])
        await self.estado.registrar(mensagem())
        job = await self.estado.obter_oferta(time.time(), True)
        self.cliente.falha = ("produto_aparicoes", "upsert", "antes")
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(job)
        self.assertEqual((await self.estado.evento(-100111, 1))["produto_id"], 1)
        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.pipeline = Pipeline(self.estado, self.repo, self.storage,
                                 TelegramFake(), self.cache, self.config)
        self.pipeline.iniciar()

        async def finalizou() -> bool:
            return bool((await self.estado.evento(-100111, 1))["finalizado_em"])

        await aguardar(finalizou)
        evento = await self.estado.evento(-100111, 1)
        self.assertEqual(evento["estado"], "duplicata")
        self.assertEqual(evento["resultado"], "duplicado")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 2)
