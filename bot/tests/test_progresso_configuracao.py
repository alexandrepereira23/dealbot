"""VAL-ET2-005: interleavings locais, não reprodução do timeout histórico."""

import asyncio
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.cache import CacheFiltros
from src.config import Config
from src.dedup import gerar_hash
from src.estado import EstadoLocal
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, aguardar, mensagem
from tests.test_repository import ClienteFake


class TestProgressoConfiguracao(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "estado"
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        await self.estado.configurar_canal(-100111, "Canal", 123, time.time() - 86400)
        self.cliente = ClienteFake()
        self.repo = RepositorioSupabase(self.cliente)
        self.cache = CacheFiltros(self.repo)  # None, ainda sem snapshot válido.
        config = replace(Config(), state_dir=self.dir, oferta_workers=2, retry_base=0.01,
                         retry_max=0.02, shutdown_timeout=0.02)
        self.pipeline = Pipeline(self.estado, self.repo, StorageFake(), TelegramFake(),
                                 self.cache, config)

    async def asyncTearDown(self) -> None:
        try:
            if not self.pipeline.parando:
                await self.pipeline.encerrar()
        finally:
            await self.estado.fechar()
            self.tmp.cleanup()

    def conferir_sem_gravacao_remota(self) -> None:
        self.assertEqual(self.cliente.tabelas["produtos"], [])
        self.assertEqual(self.cliente.tabelas["produto_aparicoes"], [])
        self.assertFalse(any(operacao in ("upsert", "update")
                             for _, operacao, _ in self.cliente.consultas))

    async def preparar_aguardando_config(self) -> None:
        # Precondição durável pelos métodos reais, antes de iniciar os dois leitores.
        self.assertIsNone(self.cache.filtros)
        await self.pipeline.receber(mensagem())
        job = await self.estado.obter_oferta(time.time(), False)
        self.assertIsNotNone(job)
        await self.pipeline._oferta(job)
        evento = await self.estado.evento(-100111, 1)
        self.assertEqual(evento["estado"], "aguardando_config")
        self.assertEqual(evento["tentativas"], 1)
        self.assertIsNone(evento["decisao"])
        self.assertIsNone(evento["hash"])
        self.assertEqual(json.loads(evento["diagnostico"]), {})
        self.conferir_sem_gravacao_remota()

    async def finalizada(self) -> bool:
        evento = await self.estado.evento(-100111, 1)
        return bool(evento and evento["finalizado_em"])

    async def conferir_aprovada(self) -> dict:
        evento = await self.estado.evento(-100111, 1)
        self.assertEqual(evento["estado"], "aprovada")
        self.assertEqual(evento["tentativas"], 2)
        self.assertEqual(evento["resultado"], "novo")
        self.assertIsNone(evento["erro"])
        self.assertIsNotNone(evento["finalizado_em"])
        self.assertIsNotNone(evento["disponibilizado_em"])
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)
        produto = self.cliente.tabelas["produtos"][0]
        aparicao = self.cliente.tabelas["produto_aparicoes"][0]
        self.assertEqual(evento["produto_id"], produto["id"])
        self.assertEqual(aparicao["produto_id"], produto["id"])
        decisao = json.loads(evento["decisao"])
        self.assertEqual(decisao["link"], "https://loja.test/1")
        self.assertEqual(evento["hash"], gerar_hash(decisao))
        self.assertEqual(evento["hash"], produto["dedup_hash"])
        diagnostico = json.loads(evento["diagnostico"])
        self.assertTrue(diagnostico["aceita"])
        self.assertEqual(diagnostico["motivo"], "aceita_sem_interesses")
        self.assertEqual(diagnostico["snapshot"], self.cache.versao)
        self.assertEqual(diagnostico["por_regra"], [])
        self.assertIsNone(diagnostico["regra"])
        for tabela in ("produtos", "produto_aparicoes"):
            self.assertEqual(sum(t == tabela and op == "upsert"
                                 for t, op, _ in self.cliente.consultas), 1)
        self.assertIsNotNone(self.pipeline.fatal)
        self.assertFalse(self.pipeline.fatal.done())
        return evento

    async def test_refresh_entre_select_sem_config_e_retorno_none(self) -> None:
        await self.preparar_aguardando_config()
        consultaram = asyncio.Event()
        liberar_retornos = asyncio.Event()
        leitores = set()
        obter = self.estado.obter_oferta

        async def obter_com_barreira(agora, config_valida):
            resultado = await obter(agora, config_valida)
            if not config_valida:
                self.assertIsNone(resultado)
                leitores.add(asyncio.current_task().get_name())
                if len(leitores) == 2:
                    consultaram.set()
                await liberar_retornos.wait()
            return resultado

        with patch.object(self.estado, "obter_oferta", new=obter_com_barreira):
            try:
                self.pipeline.iniciar()
                await asyncio.wait_for(consultaram.wait(), 3)
                self.assertEqual(leitores, {"oferta-0", "oferta-1"})
                self.assertIsNone(self.cache.filtros)
                self.conferir_sem_gravacao_remota()
                await self.cache.atualizar()
                self.assertEqual(self.cache.filtros, [])
                self.pipeline.acordar_ofertas.set()
                self.assertTrue(self.pipeline.acordar_ofertas.is_set())
                liberar_retornos.set()
                await aguardar(self.finalizada)
                await self.conferir_aprovada()
            finally:
                liberar_retornos.set()
                await self.pipeline.encerrar()

    async def test_refresh_entre_proxima_none_e_event_wait(self) -> None:
        await self.preparar_aguardando_config()
        consultaram = asyncio.Event()
        liberar_retornos = asyncio.Event()
        leitores = set()
        proxima = self.estado.proxima_tentativa

        async def proxima_com_barreira(classe, config_valida=True):
            resultado = await proxima(classe, config_valida)
            if classe == "oferta" and not config_valida:
                self.assertIsNone(resultado)
                leitores.add(asyncio.current_task().get_name())
                if len(leitores) == 2:
                    consultaram.set()
                await liberar_retornos.wait()
            return resultado

        with patch.object(self.estado, "proxima_tentativa", new=proxima_com_barreira):
            try:
                self.pipeline.iniciar()
                await asyncio.wait_for(consultaram.wait(), 3)
                self.assertEqual(leitores, {"oferta-0", "oferta-1"})
                self.assertIsNone(self.cache.filtros)
                self.conferir_sem_gravacao_remota()
                await self.cache.atualizar()
                self.assertEqual(self.cache.filtros, [])
                self.pipeline.acordar_ofertas.set()
                liberar_retornos.set()
                await aguardar(self.finalizada)
                await self.conferir_aprovada()
            finally:
                liberar_retornos.set()
                await self.pipeline.encerrar()

    async def test_outro_worker_limpa_evento_mas_select_valido_garante_progresso(self) -> None:
        await self.preparar_aguardando_config()
        consultou_zero = asyncio.Event()
        consultou_um = asyncio.Event()
        liberar_zero = asyncio.Event()
        retornou_zero = asyncio.Event()
        antes_select_um = asyncio.Event()
        liberar_select_um = asyncio.Event()
        reconsultou_zero = asyncio.Event()
        proxima = self.estado.proxima_tentativa
        obter = self.estado.obter_oferta
        evento = self.pipeline.acordar_ofertas

        async def proxima_com_barreira(classe, config_valida=True):
            resultado = await proxima(classe, config_valida)
            if classe == "oferta" and not config_valida:
                self.assertIsNone(resultado)
                if asyncio.current_task().get_name() == "oferta-0":
                    consultou_zero.set()
                    await liberar_zero.wait()
                    retornou_zero.set()
                else:
                    consultou_um.set()
            return resultado

        async def obter_com_barreira(agora, config_valida):
            nome = asyncio.current_task().get_name()
            if config_valida and nome == "oferta-1":
                # Única barreira anterior ao SQL: observar o clear REAL do loop.
                self.assertFalse(evento.is_set())
                antes_select_um.set()
                await liberar_select_um.wait()
            resultado = await obter(agora, config_valida)
            if config_valida and nome == "oferta-0":
                self.assertIsNone(resultado)
                reconsultou_zero.set()
            return resultado

        with patch.object(self.estado, "proxima_tentativa", new=proxima_com_barreira), \
                patch.object(self.estado, "obter_oferta", new=obter_com_barreira):
            try:
                self.pipeline.iniciar()
                await asyncio.wait_for(consultou_zero.wait(), 3)
                await asyncio.wait_for(consultou_um.wait(), 3)
                # Python 3.12: somente observar o Event real; não substituir wait/clear.
                self.assertEqual(len(evento._waiters), 1)
                self.assertFalse(evento.is_set())
                self.conferir_sem_gravacao_remota()
                await self.cache.atualizar()
                self.assertEqual(self.cache.filtros, [])
                evento.set()
                await asyncio.wait_for(antes_select_um.wait(), 3)
                self.assertFalse(evento.is_set())
                self.assertEqual((await self.estado.evento(-100111, 1))["estado"],
                                 "aguardando_config")
                liberar_zero.set()
                await asyncio.wait_for(retornou_zero.wait(), 3)
                self.assertFalse(evento.is_set())
                self.assertEqual(len(evento._waiters), 1)
                # Zero agora espera o evento já limpo; um ainda não fez o SELECT.
                liberar_select_um.set()
                await aguardar(self.finalizada)
                # Só a finalização interna pode ter acordado zero: sem nova recepção/set.
                await asyncio.wait_for(reconsultou_zero.wait(), 3)
                await self.conferir_aprovada()
            finally:
                liberar_zero.set()
                liberar_select_um.set()
                await self.pipeline.encerrar()

    async def test_refresh_apos_adiar_duravel_antes_de_retornar_ao_worker(self) -> None:
        gravou_espera = asyncio.Event()
        liberar_adiar = asyncio.Event()
        retornou_adiar = asyncio.Event()
        outro_esperando = asyncio.Event()
        reconsultou_primeiro = asyncio.Event()
        primeiro = None
        aprovador = None
        adiar = self.estado.adiar_oferta
        obter = self.estado.obter_oferta
        proxima = self.estado.proxima_tentativa

        async def adiar_com_barreira(job, estado, proxima, erro):
            nonlocal primeiro
            resultado = await adiar(job, estado, proxima, erro)
            if estado == "aguardando_config":
                primeiro = asyncio.current_task().get_name()
                gravou_espera.set()
                await liberar_adiar.wait()
                retornou_adiar.set()
            return resultado

        async def obter_observado(agora, config_valida):
            nonlocal aprovador
            resultado = await obter(agora, config_valida)
            nome = asyncio.current_task().get_name()
            if resultado is not None and resultado["tentativas"] == 2:
                aprovador = nome
            if retornou_adiar.is_set() and nome == primeiro:
                self.assertIsNone(resultado)
                reconsultou_primeiro.set()
            return resultado

        async def proxima_observada(classe, config_valida=True):
            resultado = await proxima(classe, config_valida)
            if classe == "oferta" and not config_valida and resultado is None:
                outro_esperando.set()
            return resultado

        with patch.object(self.estado, "adiar_oferta", new=adiar_com_barreira), \
                patch.object(self.estado, "obter_oferta", new=obter_observado), \
                patch.object(self.estado, "proxima_tentativa", new=proxima_observada):
            try:
                await self.pipeline.receber(mensagem())
                self.pipeline.iniciar()
                await asyncio.wait_for(gravou_espera.wait(), 3)
                await asyncio.wait_for(outro_esperando.wait(), 3)
                pendente = await self.estado.evento(-100111, 1)
                self.assertEqual(pendente["estado"], "aguardando_config")
                self.assertEqual(pendente["tentativas"], 1)
                self.assertIsNone(pendente["decisao"])
                self.assertIsNone(pendente["hash"])
                self.assertEqual(json.loads(pendente["diagnostico"]), {})
                self.assertIsNone(self.cache.filtros)
                self.conferir_sem_gravacao_remota()
                await self.cache.atualizar()
                self.assertEqual(self.cache.filtros, [])
                self.pipeline.acordar_ofertas.set()
                await aguardar(self.finalizada)
                self.assertFalse(retornou_adiar.is_set())
                self.assertEqual({primeiro, aprovador}, {"oferta-0", "oferta-1"})
                aprovado = await self.conferir_aprovada()
                liberar_adiar.set()
                await asyncio.wait_for(reconsultou_primeiro.wait(), 3)
                self.assertEqual(await self.conferir_aprovada(), aprovado)
            finally:
                liberar_adiar.set()
                await self.pipeline.encerrar()
