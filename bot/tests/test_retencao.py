"""Retenção local com SQLite real, sem alterar retenção ou dados remotos."""

import asyncio
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.main import limpar_ciclo, manutencao
from src.modelos import FalhaLocal
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, aguardar, mensagem
from tests.test_repository import ClienteFake


class TestRetencao(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.estado = EstadoLocal(Path(self.tmp.name))
        await self.estado.abrir()

    async def asyncTearDown(self) -> None:
        await self.estado.fechar()
        self.tmp.cleanup()

    async def popular(self, eventos: int, midias: int) -> None:
        # Preparação em uma transação; todas as consultas usam o executor dono.
        def op():
            db = self.estado._conexao()
            with db:
                db.executemany("""INSERT INTO eventos(canal_id,msg_id,username,remoto_canal,
                    texto,data_origem,recebido_em,origem,tem_foto,estado,finalizado_em)
                    VALUES(-100111,?,'canal','canal','descartada','2026-01-01',1,'live',0,'descartada',1)""",
                    [(n,) for n in range(1, eventos + 1)])
                db.executemany("""INSERT INTO midias(produto_id,canal_id,msg_id,chave,estado,finalizado_em)
                    VALUES(?,-100111,?,?, 'pronta',1)""",
                    [(n, n, f'{n}.jpg') for n in range(1, midias + 1)])
        await self.estado._executar(op)

    async def test_reproducao_250_eventos_uma_chamada_remove_so_um_lote(self) -> None:
        await self.popular(250, 0)
        await self.estado.limpar(2)
        self.assertEqual((await self.estado.resumo())["ofertas"], {"descartada": 150})

    async def test_ciclo_padrao_drena_250_eventos_e_350_midias(self) -> None:
        await self.popular(250, 350)
        removidos, continuar = await limpar_ciclo(self.estado, Config(), 2)
        self.assertEqual(removidos, {"eventos": 250, "midias": 350})
        self.assertFalse(continuar)
        resumo = await self.estado.resumo()
        self.assertEqual(resumo["ofertas"], {})
        self.assertEqual(resumo["midias"], {})

    async def test_orcamento_e_progresso_independente_ate_drenar(self) -> None:
        await self.popular(250, 370)
        config = replace(Config(), limpeza_max_lotes=2)
        with patch.object(self.estado, "limpar", wraps=self.estado.limpar) as limpar:
            removidos, continuar = await limpar_ciclo(self.estado, config, 2)
            self.assertEqual(limpar.await_count, 2)
            self.assertEqual(removidos, {"eventos": 200, "midias": 200})
            self.assertTrue(continuar)
            removidos, continuar = await limpar_ciclo(self.estado, config, 2)
            self.assertEqual(limpar.await_count, 4)
            self.assertEqual(removidos, {"eventos": 50, "midias": 170})
            self.assertFalse(continuar)

    async def test_drena_backlog_exclusivo_de_cada_tabela(self) -> None:
        for eventos, midias in ((250, 0), (0, 250)):
            with self.subTest(eventos=eventos, midias=midias):
                await self.popular(eventos, midias)
                removidos, continuar = await limpar_ciclo(self.estado, Config(), 2)
                self.assertEqual(removidos, {"eventos": eventos, "midias": midias})
                self.assertFalse(continuar)

    async def test_preserva_pendencias_compensacoes_hash_e_checkpoints(self) -> None:
        await self.popular(270, 270)
        await self.estado.configurar_canal(-100111, "Canal", 123, 1, ["antigo"])
        await self.estado.iniciar_varredura(-100111, 999)
        await self.estado.falhar_canal(-100111, 9999, "FloodWait")
        await self.estado.falhar_resolucao("pendente", 9999, "TimeoutError")
        canais = await self.estado.canais()
        resolucao = await self.estado.resolucao("pendente")

        def proteger():
            db = self.estado._conexao()
            with db:
                for n, estado in enumerate(("pendente", "retry", "processando", "aguardando_config"), 1):
                    db.execute("UPDATE eventos SET estado=? WHERE msg_id=?", (estado, n))
                for n, estado in enumerate(("pendente", "retry", "processando"), 5):
                    db.execute("UPDATE eventos SET produto_id=? WHERE msg_id=?", (n, n))
                    db.execute("UPDATE midias SET estado=? WHERE produto_id=?", (estado, n))
                # Compensação protege mesmo mídia em estado terminal e sua fonte.
                db.execute("UPDATE eventos SET produto_id=8 WHERE msg_id=8")
                db.execute("UPDATE midias SET compensar=1 WHERE produto_id=8")
                db.execute("INSERT INTO donos_hash VALUES('reservado',-100111,9)")
                db.execute("UPDATE eventos SET finalizado_em=2 WHERE msg_id=10")
                db.execute("UPDATE midias SET finalizado_em=2 WHERE produto_id=10")
        await self.estado._executar(proteger)
        removidos, continuar = await limpar_ciclo(self.estado, Config(), 2)
        self.assertFalse(continuar)
        self.assertEqual(removidos, {"eventos": 260, "midias": 265})
        for n in range(1, 11):
            self.assertIsNotNone(await self.estado.evento(-100111, n))
        for n in (5, 6, 7, 8, 10):
            self.assertIsNotNone(await self.estado.midia(n))
        donos = await self.estado._executar(lambda: [tuple(r) for r in
            self.estado._conexao().execute("SELECT * FROM donos_hash")])
        self.assertEqual(donos, [("reservado", -100111, 9)])
        self.assertEqual(await self.estado.canais(), canais)
        self.assertEqual(await self.estado.resolucao("pendente"), resolucao)

    async def test_agendamento_curto_cutoff_estavel_e_renovacao_apos_drenar(self) -> None:
        await self.popular(250, 350)
        # Um lote/ciclo obriga três continuações; depois o agendamento normal.
        config = replace(Config(), limpeza_max_lotes=1, retencao_dias=1)
        esperas = []
        cortes = []
        original = self.estado.limpar

        async def limpar(antes, lote):
            cortes.append(antes)
            return await original(antes, lote)

        async def dormir(segundos):
            if segundos:
                esperas.append(segundos)
                if len(esperas) == 5:
                    raise asyncio.CancelledError

        # time.time cresce entre drenagens; não entre lotes de uma drenagem.
        with patch("src.main.time", SimpleNamespace(time=Mock(side_effect=[86402, 86403]))), \
             patch("src.main.asyncio.sleep", side_effect=dormir), \
             patch.object(self.estado, "limpar", side_effect=limpar):
            with self.assertRaises(asyncio.CancelledError):
                await manutencao(self.estado, SimpleNamespace(ativos={}), config)
        self.assertEqual(esperas, [1, 1, 1, 3600, 3600])
        self.assertEqual(cortes, [2, 2, 2, 2, 3])

    async def test_ciclo_cede_execucao_mesmo_com_lotes_imediatos(self) -> None:
        executou = asyncio.Event()
        chamadas = 0

        async def limpar(antes, lote):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 1:
                asyncio.get_running_loop().call_soon(executou.set)
            else:
                self.assertTrue(executou.is_set())
            return {"eventos": lote, "midias": 0}

        config = replace(Config(), limpeza_max_lotes=2)
        await limpar_ciclo(SimpleNamespace(limpar=limpar), config, 2)
        self.assertEqual(chamadas, 2)

    async def test_oferta_nova_processa_durante_limpeza_real(self) -> None:
        await self.popular(2500, 0)
        config = replace(Config(), limpeza_lote=10, limpeza_max_lotes=100, shutdown_timeout=.05)
        cliente = ClienteFake()
        repo = RepositorioSupabase(cliente)
        cache = CacheFiltros(repo)
        await cache.atualizar()
        pipeline = Pipeline(self.estado, repo, StorageFake(), TelegramFake(), cache, config)
        chamadas = 0
        durante = []
        produtor = None
        original = self.estado.limpar
        salvar = repo.salvar_oferta

        async def limpar(antes, lote):
            nonlocal chamadas, produtor
            resultado = await original(antes, lote)
            chamadas += 1
            if chamadas == 1:
                produtor = asyncio.create_task(pipeline.receber(mensagem(9999)))
            return resultado

        async def salvar_oferta(*args, **kwargs):
            durante.append(chamadas)
            return await salvar(*args, **kwargs)

        pipeline.iniciar()
        try:
            with patch.object(self.estado, "limpar", side_effect=limpar), \
                 patch.object(repo, "salvar_oferta", side_effect=salvar_oferta):
                removidos, continuar = await limpar_ciclo(self.estado, config, 2)
                await produtor

                async def finalizou():
                    evento = await self.estado.evento(-100111, 9999)
                    return evento and evento["estado"] == "aprovada"
                await aguardar(finalizou)
            self.assertEqual(removidos, {"eventos": 1000, "midias": 0})
            self.assertTrue(continuar)
            self.assertEqual(len(cliente.tabelas["produtos"]), 1)
            self.assertEqual(len(durante), 1)
            self.assertGreaterEqual(durante[0], 1)
            self.assertLess(durante[0], 100, "Oferta precisa progredir antes de acabar o ciclo")
        finally:
            if produtor is not None:
                await produtor
            await pipeline.encerrar()

    async def test_falha_local_nao_e_absorvida_pela_manutencao(self) -> None:
        with patch.object(self.estado, "limpar", side_effect=FalhaLocal("disco")):
            with self.assertRaises(FalhaLocal):
                await manutencao(self.estado, SimpleNamespace(ativos={}), Config())

    async def test_lote_invalido_nao_vira_delete_ilimitado(self) -> None:
        for lote in (0, -1, 1001, 1.5):
            with self.subTest(lote=lote), self.assertRaises(ValueError):
                await self.estado.limpar(2, lote)


class TestConfigRetencao(unittest.TestCase):
    def test_defaults_e_ambiente(self) -> None:
        config = Config()
        self.assertEqual((config.limpeza_lote, config.limpeza_max_lotes, config.limpeza_continuacao), (100, 10, 1))
        with patch.dict(os.environ, {"BOT_LIMPEZA_LOTE": "50", "BOT_LIMPEZA_MAX_LOTES": "3",
                                    "BOT_LIMPEZA_CONTINUACAO_S": "0.5"}, clear=True):
            config = Config.carregar()
        self.assertEqual((config.limpeza_lote, config.limpeza_max_lotes, config.limpeza_continuacao), (50, 3, .5))

    def test_limites_positivos_finitos_e_contagens_inteiras(self) -> None:
        for campo in ("limpeza_lote", "limpeza_max_lotes", "limpeza_continuacao"):
            for valor in (0, -1, float("inf"), float("nan")):
                with self.subTest(campo=campo, valor=valor), self.assertRaises(ValueError):
                    replace(Config(), **{campo: valor})
        for campo, valor in (("limpeza_lote", 1001), ("limpeza_max_lotes", 101),
                             ("limpeza_lote", 1.5), ("limpeza_max_lotes", 1.5), ("limpeza_continuacao", 61)):
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ValueError):
                replace(Config(), **{campo: valor})
