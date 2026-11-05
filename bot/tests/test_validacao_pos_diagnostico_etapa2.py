"""Controles sintéticos do marcador composto de anterior no ciclo curto SDD."""

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


class TestMarcadorAnteriorComposto(unittest.TestCase):
    def setUp(self) -> None:
        rede = patch("socket.socket", side_effect=AssertionError("Rede proibida"))
        rede.start()
        self.addCleanup(rede.stop)

    def test_antes_de_completo_nao_fabrica_modelo_residual_em_especificacao(self) -> None:
        for quantidade in ("16 GB", "16 GB DDR4"):
            for separador in ("\n", " / "):
                for valor, anterior in (("3500", 3500), ("1500", None)):
                    with self.subTest(quantidade=quantidade, separador=separador, valor=valor):
                        texto = separador.join(("Notebook Dell R$ 3500",
                            f"Memória RAM: {quantidade} (antes de R$ {valor})",
                            "À vista R$ 2999,90"))
                        r = extrair_detalhado(texto)
                        self.assertIsNotNone(r.produto, r.motivos)
                        # Inline, a especificação pertence à primeira linha e
                        # deve continuar no título, como no contrato anterior.
                        titulo = ("Notebook Dell" if separador == "\n" else
                                  f"Notebook Dell - Memória RAM: {quantidade}")
                        self.assertEqual(r.produto["titulo"], titulo)
                        self.assertEqual(r.produto["preco"], 2999.9)
                        self.assertEqual(r.produto["preco_original"], anterior)
                        self.assertIn("memoria ram:", r.conteudo)
                        self.assertNotIn("antes", r.conteudo)

    def test_marca_modelo_e_condicao_continuam_descritivos(self) -> None:
        independente = extrair_detalhado("Notebook Dell R$ 3500\n"
            "Memória RAM: 16 GB Kingston Fury (antes de R$ 599)\nPor R$ 299,90")
        self.assertIsNone(independente.produto)
        self.assertIn("multiplas_ofertas", independente.motivos)
        r = extrair_detalhado("Memória RAM: 16 GB Kingston Fury (antes de R$ 599)\nPor R$ 299,90")
        self.assertEqual(r.produto["titulo"], "Memória RAM: 16 GB Kingston Fury")
        self.assertEqual((r.produto["preco"], r.produto["preco_original"]), (299.9, 599))
        regras = preparar_filtros([
            {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
            {"id": 2},
        ])
        r = avaliar_mensagem("SSD Kingston (antes de R$ 399,90) USADO\nPor R$ 299,90", regras)
        self.assertFalse(r.aceita)
        self.assertEqual(r.diagnostico["motivo"], "bloqueio_global")
        self.assertIn("usado", r.extracao.conteudo)


class TestAnteriorCompostoNoPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_especificacao_com_anterior_e_multiplos_terminalizam_corretamente(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            cliente = ClienteFake()
            repo = RepositorioSupabase(cliente)
            cache = CacheFiltros(repo)
            cache.filtros = []
            pipeline = Pipeline(estado, repo, StorageFake(), TelegramFake(), cache,
                                replace(Config(), state_dir=Path(diretorio)))
            try:
                casos = [
                    ("Notebook Dell R$ 3500\nMemória RAM: 16 GB DDR4 (antes de R$ 3500)\n"
                     "À vista R$ 2999,90", "aprovada", "aceita_sem_interesses"),
                    ("Notebook Dell R$ 3500\nMemória RAM: 16 GB Kingston Fury "
                     "(antes de R$ 599)\nPor R$ 299,90", "descartada", "multiplas_ofertas"),
                ]
                for msg_id, (texto, situacao, motivo) in enumerate(casos, 1):
                    await estado.registrar(mensagem(msg_id=msg_id, texto=texto))
                    job = await estado.obter_oferta(time.time(), True)
                    consultas = len(cliente.consultas)
                    await pipeline._oferta(job)
                    evento = await estado.evento(job["canal_id"], msg_id)
                    self.assertEqual(evento["estado"], situacao)
                    self.assertEqual(json.loads(evento["diagnostico"])["motivo"], motivo)
                    if situacao == "aprovada":
                        decisao = json.loads(evento["decisao"])
                        self.assertEqual((decisao["preco"], decisao["preco_original"]), (2999.9, 3500))
                        self.assertNotIn("conteudo", cliente.tabelas["produtos"][0])
                    else:
                        self.assertIsNone(evento["decisao"])
                        self.assertEqual(len(cliente.consultas), consultas)
                    self.assertIsNone(await estado.obter_oferta(time.time() + 10, True))
                self.assertEqual(len(cliente.tabelas["produtos"]), 1)
                self.assertEqual(len(cliente.tabelas["produto_aparicoes"]), 1)
            finally:
                await pipeline.encerrar()
                await estado.fechar()
