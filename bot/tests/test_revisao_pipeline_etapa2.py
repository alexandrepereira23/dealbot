"""Revisão da etapa 2 com inbox SQLite real e fronteira remota falsa."""

import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.avaliacao import ResultadoMensagem, avaliar_mensagem
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.filters import preparar_filtros
from src.modelos import Mensagem
from src.pipeline import Pipeline
from src.repository import CAMPOS_REMOTOS, RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, mensagem
from tests.test_repository import ClienteFake


REGRAS = [
    {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado", "recondicionado"]},
    {"id": 2, "palavras_chave": ["SSD", "Kingston"], "modo_palavras": "todas", "preco_max": 350},
]
TEXTO_A = "SSD Kingston NV2 1 TB\nPor R$ 299,90 no Pix (RECONDICIONADO)\nhttps://loja.example/ssd"
TEXTO_B = "SSD Kingston NV2 1 TB\nR$ 299,90 à vista USADO\nhttps://loja.example/ssd"
TEXTO_FRETE = "SSD Kingston NV2 1 TB\nR$ 299,90\nFrete para Goiânia R$ 15,00\nhttps://loja.example/ssd"


class TestRevisaoPipelineEtapa2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self.tmp.name)
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.cliente = ClienteFake()
        self.repo = RepositorioSupabase(self.cliente)
        self.cache = CacheFiltros(self.repo)
        self.cache.filtros = REGRAS
        self.config = replace(Config(), state_dir=self.diretorio, shutdown_timeout=0.01)
        self.pipeline = Pipeline(self.estado, self.repo, StorageFake(), TelegramFake(), self.cache, self.config)

    async def asyncTearDown(self) -> None:
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    def entrada(self, texto: str, msg_id: int, origem: str) -> Mensagem:
        contexto = {"versao": 1, "links": [
            {"url": "https://loja.example/ssd", "origem": "botao", "rotulo": "Comprar"},
        ], "codigos": [], "exclusoes": []}
        return replace(mensagem(texto=texto, msg_id=msg_id, origem=origem), contexto=contexto)

    async def reiniciar(self) -> None:
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.repo = RepositorioSupabase(self.cliente)
        self.pipeline = Pipeline(self.estado, self.repo, StorageFake(), TelegramFake(), self.cache, self.config)

    async def persistir_antes_de_avaliar(self, entrada: Mensagem) -> tuple[dict, ResultadoMensagem]:
        filtros = preparar_filtros(REGRAS)
        esperado = avaliar_mensagem(entrada.texto, filtros, entrada.contexto,
                                   canal_id=entrada.canal_id, username=entrada.username)
        self.assertEqual(esperado.extracao.fonte_link, "botao")
        self.assertTrue(await self.estado.registrar(entrada))
        await self.reiniciar()
        job = await self.estado.obter_oferta(time.time(), True)
        self.assertIsNotNone(job)
        self.assertEqual((job["canal_id"], job["msg_id"], job["origem"]),
                         (entrada.canal_id, entrada.msg_id, entrada.origem))
        self.assertEqual(job["texto"], entrada.texto)
        contexto = json.loads(job["contexto"])
        self.assertEqual(contexto, entrada.contexto)
        self.assertTrue(contexto["links"])
        self.assertIsNone(job["decisao"])
        self.assertIsNone(job["hash"])
        self.assertEqual(esperado, avaliar_mensagem(job["texto"], filtros, contexto,
                         canal_id=job["canal_id"], username=job["username"]))
        return job, esperado

    async def conferir_finalizado_inalterado(self, entrada: Mensagem) -> None:
        antes = await self.estado.evento(entrada.canal_id, entrada.msg_id)
        self.assertIsNotNone(antes["finalizado_em"])
        consultas = list(self.cliente.consultas)
        await self.reiniciar()
        self.assertEqual(await self.estado.evento(entrada.canal_id, entrada.msg_id), antes)
        duplicata = replace(entrada, origem="historico" if entrada.origem == "live" else "live",
                            texto="Não substituir mensagem finalizada", contexto={})
        self.assertFalse(await self.estado.registrar(duplicata))
        self.assertEqual(await self.estado.evento(entrada.canal_id, entrada.msg_id), antes)
        self.assertIsNone(await self.estado.obter_oferta(time.time() + 100, True))
        self.assertEqual(self.cliente.consultas, consultas)

    async def conferir_matriz(self, origem: str) -> None:
        for msg_id, (texto, condicao) in enumerate([
            (TEXTO_A, "recondicionado"), (TEXTO_B, "usado"), (TEXTO_FRETE, None),
        ], 1):
            with self.subTest(origem=origem, msg_id=msg_id):
                entrada = self.entrada(texto, msg_id, origem)
                job, esperado = await self.persistir_antes_de_avaliar(entrada)
                consultas = list(self.cliente.consultas)
                await self.pipeline._oferta(job)
                evento = await self.estado.evento(entrada.canal_id, msg_id)
                diagnostico = json.loads(evento["diagnostico"])
                self.assertEqual(diagnostico, {**esperado.diagnostico, "snapshot": self.cache.versao})
                await self.conferir_finalizado_inalterado(entrada)
                self.assertIsNotNone(esperado.extracao.produto, esperado.diagnostico)
                self.assertEqual(esperado.extracao.produto["preco"], 299.9)
                self.assertIsNone(esperado.extracao.produto["preco_original"])
                if condicao:
                    self.assertFalse(esperado.aceita, esperado.diagnostico)
                    self.assertIn(condicao, esperado.extracao.conteudo)
                    self.assertEqual(evento["estado"], "descartada")
                    self.assertEqual(diagnostico["motivo"], "bloqueio_global")
                    self.assertEqual(diagnostico["regra"], 1)
                    self.assertIsNone(evento["decisao"])
                    self.assertIsNone(evento["hash"])
                    self.assertEqual(self.cliente.consultas, consultas)
                    self.assertEqual(self.cliente.tabelas["produtos"], [])
                    self.assertEqual(self.cliente.tabelas["produto_aparicoes"], [])
                else:
                    self.assertTrue(esperado.aceita, esperado.diagnostico)
                    self.assertEqual(evento["estado"], "aprovada")
                    self.assertEqual(diagnostico["motivo"], "aceita_por_regra")
                    self.assertEqual(diagnostico["regra"], 2)
                    self.assertNotIn("preco_ambiguo", esperado.extracao.motivos)
                    self.assertEqual(json.loads(evento["decisao"]), esperado.extracao.produto)
                    self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
                    self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)
                    produto = self.cliente.tabelas["produtos"][0]
                    self.assertEqual(produto["preco"], 299.9)
                    self.assertIsNone(produto["preco_original"])
                    self.assertEqual(produto["dedup_hash"], evento["hash"])
                    self.assertTrue(set(produto) <= set(CAMPOS_REMOTOS) | {"id", "criado_em"})

    async def test_live_veto_pagamento_e_preco_frete_apos_retomar_contexto(self) -> None:
        await self.conferir_matriz("live")

    async def test_historico_veto_pagamento_e_preco_frete_apos_retomar_contexto(self) -> None:
        await self.conferir_matriz("historico")

    async def test_frete_timeout_pos_upsert_retoma_checkpoint_sem_reavaliar(self) -> None:
        entrada = self.entrada(TEXTO_FRETE, 10, "historico")
        job, esperado = await self.persistir_antes_de_avaliar(entrada)
        self.assertTrue(esperado.aceita, esperado.diagnostico)
        self.cliente.falha = ("produtos", "upsert", "depois")
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(job)
        antes = await self.estado.evento(entrada.canal_id, entrada.msg_id)
        self.assertIsNone(antes["finalizado_em"])
        self.assertIsNone(antes["produto_id"])
        self.assertEqual(json.loads(antes["decisao"]), esperado.extracao.produto)
        self.assertEqual(json.loads(antes["diagnostico"]),
                         {**esperado.diagnostico, "snapshot": self.cache.versao})
        self.assertIsNotNone(antes["hash"])
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(self.cliente.tabelas["produtos"][0]["preco"], 299.9)
        self.assertEqual(self.cliente.tabelas["produto_aparicoes"], [])
        # A reconciliação é pelo evento, não pela janela temporal de deduplicação.
        self.cliente.tabelas["produtos"][0]["criado_em"] = "2000-01-01T00:00:00+00:00"
        self.cache.filtros = None
        with ExitStack() as guardas:
            for alvo in ("src.pipeline.avaliar_mensagem", "src.avaliacao.extrair_detalhado",
                         "src.avaliacao.avaliar_produto", "src.pipeline.gerar_hash",
                         "src.repository.gerar_hash"):
                guardas.enter_context(patch(alvo, side_effect=AssertionError("Checkpoint reavaliado: " + alvo)))
            await self.reiniciar()
            job = await self.estado.obter_oferta(time.time(), False)
            self.assertIsNotNone(job, "Decisão congelada retoma mesmo sem configuração")
            for campo in ("decisao", "diagnostico", "hash", "contexto"):
                self.assertEqual(job[campo], antes[campo])
            await self.pipeline._oferta(job)
        evento = await self.estado.evento(entrada.canal_id, entrada.msg_id)
        self.assertEqual(evento["estado"], "aprovada")
        self.assertEqual(evento["tentativas"], 2)
        for campo in ("decisao", "diagnostico", "hash", "contexto"):
            self.assertEqual(evento[campo], antes[campo])
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)
        produto = self.cliente.tabelas["produtos"][0]
        aparicao = self.cliente.tabelas["produto_aparicoes"][0]
        self.assertEqual(produto["dedup_hash"], antes["hash"])
        self.assertEqual(produto["preco"], 299.9)
        self.assertIsNone(produto["preco_original"])
        self.assertEqual(evento["produto_id"], produto["id"])
        self.assertEqual(aparicao["produto_id"], produto["id"])
        self.assertEqual(aparicao["telegram_msg_id"], entrada.msg_id)
        self.assertTrue(set(produto) <= set(CAMPOS_REMOTOS) | {"id", "criado_em"})
        self.assertEqual(sum(tabela == "produtos" and operacao == "upsert"
                             for tabela, operacao, _ in self.cliente.consultas), 1)
        await self.conferir_finalizado_inalterado(entrada)
