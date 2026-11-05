"""Regressões sintéticas do ciclo curto da validação de 2026-11-05."""

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.avaliacao import avaliar_mensagem
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.extractor import extrair_detalhado
from src.filters import preparar_filtros
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, mensagem
from tests.test_repository import ClienteFake


REGRAS = [
    {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
    {"id": 2},
]


class TestVirgulaDeClausula(unittest.TestCase):
    def setUp(self) -> None:
        rede = patch("socket.socket", side_effect=AssertionError("Rede proibida"))
        rede.start()
        self.addCleanup(rede.stop)

    def test_veto_apos_servico_com_virgula_sem_espaco(self) -> None:
        regras = preparar_filtros(REGRAS)
        for cauda in (",USADO", ", USADO", ",\u00a0USADO", ", (USADO)",
                      ", [USADO]", ', "USADO"', ",(USADO)", ",[USADO]"):
            with self.subTest(cauda=cauda):
                r = avaliar_mensagem("SSD Kingston R$ 299,90 - Frete a calcular" + cauda, regras)
                self.assertFalse(r.aceita, r.diagnostico)
                self.assertEqual(r.diagnostico["motivo"], "bloqueio_global")
                self.assertEqual(r.diagnostico["regra"], 1)
                self.assertIn("usado", r.extracao.conteudo)

    def test_virgula_decimal_e_formato_ambiguo_nao_sao_separadores(self) -> None:
        for valor, esperado in (("299,90", 299.9), ("1.234,56", 1234.56),
                                ("1,234", None), ("1, 234", None), ("1,\u00a0234", None)):
            with self.subTest(valor=valor):
                r = extrair_detalhado("SSD Kingston\nR$ " + valor + "\nhttps://loja.example/ssd")
                self.assertIsNotNone(r.produto, r.motivos)
                self.assertEqual(r.produto["preco"], esperado)
                if esperado is None:
                    self.assertIn("formato_preco_ambiguo", r.motivos)

    def test_codigo_e_url_apos_virgula_nao_viram_condicao(self) -> None:
        regras = preparar_filtros(REGRAS)
        for cauda in ("Cupom:USADO", "https://loja.example/USADO"):
            with self.subTest(cauda=cauda):
                r = avaliar_mensagem("SSD Kingston R$ 299,90 - Frete a calcular," + cauda, regras)
                self.assertTrue(r.aceita, r.diagnostico)
                self.assertNotIn("usado", r.extracao.conteudo)


class TestVirgulaNoPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_veto_persiste_sem_salvar_oferta_ou_retentar(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            cliente = ClienteFake()
            repo = RepositorioSupabase(cliente)
            cache = CacheFiltros(repo)
            cache.filtros = REGRAS
            pipeline = Pipeline(estado, repo, StorageFake(), TelegramFake(), cache,
                                replace(Config(), state_dir=Path(diretorio)))
            try:
                await estado.registrar(mensagem(texto="SSD Kingston R$ 299,90 - Frete a calcular,USADO"))
                job = await estado.obter_oferta(time.time(), True)
                consultas = len(cliente.consultas)
                await pipeline._oferta(job)
                evento = await estado.evento(job["canal_id"], job["msg_id"])
                self.assertEqual(evento["estado"], "descartada")
                self.assertEqual(json.loads(evento["diagnostico"])["motivo"], "bloqueio_global")
                self.assertIsNone(evento["decisao"])
                self.assertEqual(len(cliente.consultas), consultas)
                self.assertEqual(cliente.tabelas["produtos"], [])
                self.assertIsNone(await estado.obter_oferta(time.time() + 10, True))
            finally:
                await pipeline.encerrar()
                await estado.fechar()
