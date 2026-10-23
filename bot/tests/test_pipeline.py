"""Comportamentos da fila real SQLite com integrações falsas, sem credenciais."""

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.modelos import Aguardar, ErroPermanente, FalhaLocal, Mensagem
from src.pipeline import Pipeline
from src.politica import classificar
from src.repository import RepositorioSupabase
from tests.test_repository import ClienteFake


def mensagem(msg_id: int = 1, canal: int = -100111, foto: bool = False,
             origem: str = "live", texto: str | None = None) -> Mensagem:
    return Mensagem(canal, msg_id, "Canal", texto or f"Notebook promoção R$ 99,90 https://loja.test/{msg_id}",
                    "2026-10-22T12:00:00+00:00", foto, origem)


async def aguardar(condicao, timeout: float = 3) -> None:
    async def conferir() -> None:
        while not await condicao():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(conferir(), timeout)


class StorageFake:
    def __init__(self) -> None:
        self.objetos = {}
        self.falhar_envio = False
        self.falhar_remocao = False
        self.removidos = []

    async def enviar(self, chave: str, dados: bytes) -> str:
        self.objetos[chave] = dados
        if self.falhar_envio:
            self.falhar_envio = False
            raise TimeoutError("TOKEN_NAO_LOGAR")
        return "https://storage.test/" + chave

    async def remover(self, chave: str) -> None:
        if self.falhar_remocao:
            self.falhar_remocao = False
            raise ErroPermanente("falha_fake")
        self.objetos.pop(chave, None)
        self.removidos.append(chave)


class TelegramFake:
    def __init__(self) -> None:
        self.iniciou = asyncio.Event()
        self.liberar = asyncio.Event()
        self.liberar.set()
        self.chamadas = 0

    async def baixar_foto(self, canal_id: int, msg_id: int, max_bytes: int) -> bytes:
        self.chamadas += 1
        self.iniciou.set()
        await self.liberar.wait()
        return b"foto"


class TestPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "estado"
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        await self.estado.configurar_canal(-100111, "Canal", 123, time.time() - 86400)
        self.cliente = ClienteFake()
        self.repo = RepositorioSupabase(self.cliente)
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.storage = StorageFake()
        self.telegram = TelegramFake()
        self.config = replace(Config(), state_dir=self.dir, oferta_workers=2, retry_base=0.01,
                              retry_max=0.02, shutdown_timeout=0.02)
        self.pipeline = Pipeline(self.estado, self.repo, self.storage, self.telegram, self.cache, self.config)

    async def asyncTearDown(self) -> None:
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def finalizada(self, canal: int, msg: int) -> bool:
        evento = await self.estado.evento(canal, msg)
        return bool(evento and evento["finalizado_em"])

    async def test_live_e_historico_mesma_id_um_processamento_e_reinicio(self) -> None:
        await self.pipeline.receber(mensagem(origem="historico"))
        await self.pipeline.receber(mensagem())
        original = await self.estado.evento(-100111, 1)
        self.pipeline.iniciar()
        await aguardar(lambda: self.finalizada(-100111, 1))
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        self.pipeline = Pipeline(self.estado, self.repo, self.storage, self.telegram, self.cache, self.config)
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem())
        await asyncio.sleep(0.02)
        evento = await self.estado.evento(-100111, 1)
        self.assertEqual(evento["recebido_em"], original["recebido_em"])
        self.assertEqual(evento["tentativas"], 1)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)

    async def test_foto_lenta_oferta_salva_primeiro_e_shutdown_retomavel(self) -> None:
        self.telegram.liberar.clear()
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))
        await asyncio.wait_for(self.telegram.iniciou.wait(), 2)
        produto = self.cliente.tabelas["produtos"][0]
        self.assertIsNone(produto["foto_url"])
        self.assertTrue(await self.finalizada(-100111, 1))
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        self.telegram.liberar.set()
        self.pipeline = Pipeline(self.estado, self.repo, self.storage, self.telegram, self.cache, self.config)
        self.pipeline.iniciar()
        async def pronta() -> bool:
            return bool(produto["foto_url"])
        await aguardar(pronta)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.storage.objetos), 1)

    async def test_erro_upload_apos_commit_compensa_e_retenta_sem_orfao(self) -> None:
        self.storage.falhar_envio = True
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))
        async def pronta() -> bool:
            return bool(self.cliente.tabelas["produtos"] and self.cliente.tabelas["produtos"][0]["foto_url"])
        await aguardar(pronta)
        self.assertEqual(len(self.storage.objetos), 1)
        self.assertEqual(len(self.storage.removidos), 1)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_upload_permanente_compensa_antes_de_terminalizar_sem_loop(self) -> None:
        self.storage.enviar = AsyncMock(side_effect=ErroPermanente("midia_excede_limite"))
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))
        async def terminou() -> bool:
            midia = await self.estado.midia(1)
            return bool(midia and midia["estado"] == "falha_permanente" and not midia["compensar"])
        await aguardar(terminou)
        self.assertEqual(self.storage.enviar.await_count, 1)
        self.assertEqual(len(self.storage.removidos), 1)
        self.assertEqual((await self.estado.midia(1))["erro"], "midia_excede_limite")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_falha_config_inicial_nao_aceita_tudo_e_refresh_preserva_snapshot(self) -> None:
        self.cache.filtros = None
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem())
        async def esperando() -> bool:
            return (await self.estado.evento(-100111, 1))["estado"] == "aguardando_config"
        await aguardar(esperando)
        self.assertEqual(self.cliente.tabelas["produtos"], [])
        await self.cache.atualizar()  # [] válido
        self.pipeline.acordar_ofertas.set()
        await aguardar(lambda: self.finalizada(-100111, 1))
        self.cliente.tabelas["filtros"] = [{"ativo": True, "palavras_bloqueio": ["notebook"]}]
        await self.cache.atualizar()
        self.cliente.falha = ("filtros", "select", "antes")
        with self.assertRaises(TimeoutError):
            await self.cache.atualizar()
        await self.pipeline.receber(mensagem(2))
        await aguardar(lambda: self.finalizada(-100111, 2))
        self.assertEqual((await self.estado.evento(-100111, 2))["estado"], "descartada")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_decisao_nao_muda_entre_commit_remoto_ambiguo_e_retry(self) -> None:
        self.cliente.falha = ("produtos", "upsert", "depois")
        await self.estado.registrar(mensagem())
        job = await self.estado.obter_oferta(time.time(), True)
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(job)
        await self.estado.adiar_oferta(job, "retry", 0, "TimeoutError")
        self.cache.filtros = [{"palavras_bloqueio": ["notebook"]}]
        self.pipeline.iniciar()
        await aguardar(lambda: self.finalizada(-100111, 1))
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual((await self.estado.evento(-100111, 1))["estado"], "aprovada")

    async def test_vinculo_antes_da_aparicao_sobrevive_mais_de_48h(self) -> None:
        await self.repo.salvar_oferta({"titulo": "Notebook", "preco": 99.9,
            "link": "https://loja.test/1", "canal_origem": "outro", "telegram_msg_id": 80, "foto_url": None}, [])
        await self.estado.registrar(mensagem())
        job = await self.estado.obter_oferta(time.time(), True)
        self.cliente.falha = ("produto_aparicoes", "upsert", "antes")
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(job)
        evento = await self.estado.evento(-100111, 1)
        self.assertIsNotNone(evento["produto_id"])
        self.cliente.tabelas["produtos"][0]["criado_em"] = "2000-01-01T00:00:00+00:00"
        await self.estado.adiar_oferta(job, "retry", 0, "TimeoutError")
        self.pipeline.iniciar()
        await aguardar(lambda: self.finalizada(-100111, 1))
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 2)

    async def test_hash_duravel_impede_outro_canal_durante_falha_ambigua(self) -> None:
        await self.estado.registrar(mensagem())
        job = await self.estado.obter_oferta(time.time(), True)
        self.cliente.falha = ("produtos", "upsert", "depois")
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(job)
        await self.estado.registrar(mensagem(canal=-100222))
        outro = await self.estado.obter_oferta(time.time(), True)
        with self.assertRaises(Aguardar):
            await self.pipeline._oferta(outro)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_retencao_preserva_pendencias_midia_retry_e_fronteiras(self) -> None:
        for n in range(1, 5):
            await self.estado.registrar(mensagem(n, foto=True))
        for n in (1, 2, 3):
            job = await self.estado.evento(-100111, n)
            await self.estado.finalizar_oferta(job, "aprovada", n, midia=n == 2)
        await self.estado.atualizar_midia(2, estado="retry", proxima=time.time() + 10000)
        antes = time.time() + 1
        removidos = await self.estado.limpar(antes)
        self.assertEqual(removidos, 2)
        self.assertIsNotNone(await self.estado.evento(-100111, 2))
        self.assertIsNotNone(await self.estado.evento(-100111, 4))
        self.assertEqual(len(await self.estado.canais()), 1)

    async def test_falha_pagina_rollback_nao_avanca_marcador(self) -> None:
        await self.estado.iniciar_varredura(-100111, 10)
        original = self.estado._inserir
        chamadas = 0
        def falhar(msg):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 2:
                raise sqlite3.OperationalError("disco cheio")
            return original(msg)
        with patch.object(self.estado, "_inserir", side_effect=falhar):
            with self.assertRaises(FalhaLocal):
                await self.estado.registrar_pagina(-100111, [mensagem(1), mensagem(2)], 2, False, 0)
        self.assertIsNone(await self.estado.evento(-100111, 1))
        self.assertEqual((await self.estado.canal(-100111))["cursor"], 0)
        await self.estado.registrar_pagina(-100111, [mensagem(1), mensagem(2)], 2, False, 0)
        self.assertEqual((await self.estado.canal(-100111))["cursor"], 2)

    async def test_segunda_instancia_rejeitada_claim_interrompido_retomado(self) -> None:
        segunda = EstadoLocal(self.dir)
        with self.assertRaises(FalhaLocal):
            await segunda.abrir()
        await self.estado.registrar(mensagem())
        await self.estado.obter_oferta(time.time(), True)
        await self.estado.fechar()
        self.estado = EstadoLocal(self.dir)
        await self.estado.abrir()
        self.pipeline = Pipeline(self.estado, self.repo, self.storage, self.telegram, self.cache, self.config)
        self.pipeline.iniciar()
        await aguardar(lambda: self.finalizada(-100111, 1))
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)

    async def test_produto_removido_apos_upload_compensa_sem_ressuscitar(self) -> None:
        self.telegram.liberar.clear()
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem(foto=True))
        await self.telegram.iniciou.wait()
        self.cliente.tabelas["produtos"].clear()
        self.telegram.liberar.set()
        async def removida() -> bool:
            job = await self.estado.midia(1)
            return bool(job and job["estado"] == "removida")
        await aguardar(removida)
        self.assertEqual(self.storage.objetos, {})
        self.assertEqual(self.cliente.tabelas["produtos"], [])

    async def test_rajada_concorrencia_justica_e_heartbeat(self) -> None:
        self.cliente.atraso = 0.002
        for n in range(1, 41):
            await self.estado.registrar(mensagem(n, origem="historico"))
        await self.estado.registrar(mensagem(100))
        batidas = 0
        async def heartbeat() -> None:
            nonlocal batidas
            while True:
                batidas += 1
                await asyncio.sleep(0.002)
        tarefa = asyncio.create_task(heartbeat())
        self.pipeline.iniciar()
        try:
            await aguardar(lambda: self.finalizada(-100111, 100))
            finalizados = (await self.estado.resumo())["ofertas"]
            self.assertLess(finalizados.get("aprovada", 0), 41)
            await aguardar(lambda: self.finalizada(-100111, 10))
            self.assertGreater(batidas, 5)
            self.assertLessEqual(self.pipeline.max_ativos["oferta"], 2)
            self.assertEqual(len(self.pipeline.tasks), 3)
        finally:
            tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)

    async def test_rodizio_live_entre_canais_e_cota_de_historico(self) -> None:
        for canal in (-100111, -100222):
            for n in range(1, 10):
                await self.estado.registrar(mensagem(n, canal=canal))
        await self.estado.registrar(mensagem(99, origem="historico"))
        escolhidos = [await self.estado.obter_oferta(time.time(), True) for _ in range(5)]
        self.assertEqual(len({j["canal_id"] for j in escolhidos[:2]}), 2)
        self.assertEqual(escolhidos[4]["origem"], "historico")


class TestPoliticas(unittest.TestCase):
    def test_logs_de_erro_nao_incluem_segredo_da_excecao(self) -> None:
        from src.observabilidade import log, motivo_erro
        with self.assertLogs("dealbot", level="INFO") as capturado:
            log("trabalho_falhou", motivo=motivo_erro(TimeoutError("TOKEN_SUPER_SECRETO")))
        self.assertNotIn("TOKEN_SUPER_SECRETO", "".join(capturado.output))
        self.assertIn("TimeoutError", "".join(capturado.output))

    def test_floodwait_e_permanente_e_configuracao(self) -> None:
        class FloodWait(Exception):
            seconds = 120
        self.assertGreaterEqual(classificar(FloodWait(), 1, 1, 10).espera, 120)
        self.assertTrue(classificar(ErroPermanente("midia_excede_limite"), 1, 1, 10).permanente)
        self.assertFalse(classificar(TimeoutError(), 100, 1, 10).permanente)
        with self.assertRaises(ValueError):
            Config(oferta_workers=0)
        with self.assertRaises(ValueError):
            Config(recuperacao_lote=101)
