"""Controles cruzados sintéticos de VAL-ET2-001/003/004 e RNF-002."""

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src import extractor
from src.avaliacao import avaliar_mensagem
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.filters import preparar_filtros
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, mensagem
from tests.test_repository import ClienteFake


class TestSegundaRetomada(unittest.TestCase):
    def setUp(self) -> None:
        rede = patch("socket.socket", side_effect=AssertionError("Rede proibida"))
        rede.start()
        self.addCleanup(rede.stop)

    def test_servico_nao_monetario_nao_apaga_condicao_de_produto(self) -> None:
        regras = preparar_filtros([
            {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
            {"id": 2},
        ])
        for servico in ("Frete incluso", "Entrega incluída", "Envio é incluso", "Frete a calcular"):
            for separador in (", ", "; ", " / ", " - "):
                with self.subTest(servico=servico, separador=separador):
                    r = avaliar_mensagem("SSD R$ 299,90 - " + servico + separador + "USADO", regras)
                    self.assertFalse(r.aceita, r.diagnostico)
                    self.assertEqual(r.diagnostico["motivo"], "bloqueio_global")
                    self.assertIn("usado", r.extracao.conteudo)
        r = avaliar_mensagem("SSD R$ 299,90 - Frete incluso USADO", regras)
        self.assertFalse(r.aceita, r.diagnostico)

    def test_servicos_nao_fabricam_descricao_ou_match_de_produto(self) -> None:
        for trecho in ("Frete incluso", "Frete incluso para SSD", "Frete de R$ 15,00 para SSD",
                       "Desconto de R$ 50 na compra de SSD"):
            with self.subTest(trecho=trecho):
                self.assertIsNone(extractor.extrair_detalhado(trecho + "\nhttps://loja.example/oferta").produto)
        r = extractor.extrair_detalhado("SSD R$ 299,90 - Frete incluso, NV2 1 TB NVMe\n"
            "Cupom: USADO\nEntre no grupo de recondicionado https://t.me/sintetico")
        self.assertIn("nv2 1 tb nvme", r.conteudo)
        for ruido in ("usado", "frete", "recondicionado", "example"):
            self.assertNotIn(ruido, r.conteudo)

    def test_clausulas_de_um_produto_preservam_papeis_monetarios(self) -> None:
        for separador in (" / ", " - ", "; ", " | ", ", "):
            with self.subTest(separador=separador):
                texto = separador.join(("SSD Kingston - NV2 1 TB", "De R$ 399,90 por R$ 299,90",
                                        "Frete - R$ 15,00", "10x de R$ 29,99"))
                r = extractor.extrair_detalhado(texto)
                self.assertIsNotNone(r.produto, r.motivos)
                self.assertEqual((r.produto["preco"], r.produto["preco_original"]), (299.9, 399.9))
                self.assertIn("nv2 1 tb", r.conteudo)
                self.assertNotIn("multiplas_ofertas", r.motivos)

    def test_dois_produtos_independentes_por_clausula_mesmo_com_valores_iguais(self) -> None:
        for separador in (" / ", " - ", "; ", " | ", ", ", "\n"):
            for valor in ("299,90", "149,90"):
                with self.subTest(separador=separador, valor=valor):
                    r = extractor.extrair_detalhado("SSD Kingston R$ 299,90" + separador +
                                                   "Logitech Headset G435 por R$ " + valor)
                    self.assertIsNone(r.produto)
                    self.assertIn("multiplas_ofertas", r.motivos)
        r = extractor.extrair_detalhado("R$ 350 SSD Kingston / R$ 149 Headset Logitech")
        self.assertIsNone(r.produto)
        self.assertIn("multiplas_ofertas", r.motivos)

    def test_rotulos_de_componentes_sem_preco_proprio_continuam_descricao(self) -> None:
        for campo in ("Processador: Intel Core i5", "CPU: Intel Core i5", "Memória RAM: 16 GB",
                      "Placa de vídeo: RTX 4060", "SSD: Kingston 1 TB"):
            for separador in ("\n", " / "):
                with self.subTest(campo=campo, separador=separador):
                    r = extractor.extrair_detalhado(separador.join((
                        "Notebook Dell", "R$ 3500,00", campo, "À vista R$ 2999,90")))
                    self.assertIsNotNone(r.produto, r.motivos)
                    self.assertEqual(r.produto["preco"], 2999.9)
                    self.assertIn("notebook dell", r.conteudo)

    def test_processador_com_preco_proprio_nao_e_absorvido_como_campo(self) -> None:
        for separador in ("\n", " / "):
            for titulo in ("Processador: Intel Core i5 R$ 999", "Processador Intel Core i5\nPor R$ 999"):
                with self.subTest(separador=separador, titulo=titulo):
                    r = extractor.extrair_detalhado("Notebook Dell R$ 3500" + separador + titulo)
                    self.assertIsNone(r.produto)
                    self.assertIn("multiplas_ofertas", r.motivos)
        r = extractor.extrair_detalhado("Processador: Intel Core i5\nR$ 999")
        self.assertEqual(r.produto["preco"], 999)
        self.assertIn("Processador", r.produto["titulo"])

    def test_memoria_rotulada_com_marca_e_preco_posterior_e_independente(self) -> None:
        for rotulo in ("Memória RAM", "Memória RAM:"):
            with self.subTest(rotulo=rotulo):
                r = extractor.extrair_detalhado("Notebook Dell R$ 3500\nhttps://loja.example/notebook\n" +
                    rotulo + " 16 GB Kingston Fury\nPor R$ 299,90\nhttps://loja.example/memoria")
                self.assertIsNone(r.produto)
                self.assertIn("multiplas_ofertas", r.motivos)

    def test_frete_parcela_e_anterior_nao_sao_preco_proprio_de_campo(self) -> None:
        for servico in ("frete de R$ 15,00", "10x de R$ 99,90", "antes R$ 3500"):
            with self.subTest(servico=servico):
                r = extractor.extrair_detalhado("Notebook Dell R$ 3500\n"
                    "Processador: Intel Core i5 (" + servico + ")\nÀ vista R$ 2999,90")
                self.assertIsNotNone(r.produto, r.motivos)
                self.assertEqual(r.produto["preco"], 2999.9)

    def test_memoria_quantificada_continua_campo_apos_retirar_servico_parentetizado(self) -> None:
        for quantidade in ("16 GB", "16 GB DDR4"):
            for servico in ("frete de R$ 15,00", "antes R$ 3500", "10x de R$ 99,90",
                            "10x de R$ 99,90 sem juros", "Parcela de R$ 99,90 com juros"):
                with self.subTest(quantidade=quantidade, servico=servico):
                    r = extractor.extrair_detalhado("Notebook Dell R$ 3500\nMemória RAM: " + quantidade +
                        " (" + servico + ")\nÀ vista R$ 2999,90")
                    self.assertIsNotNone(r.produto, r.motivos)
                    self.assertEqual(r.produto["preco"], 2999.9)
        independente = extractor.extrair_detalhado("Notebook Dell R$ 3500\n"
            "Memória RAM: 16 GB Kingston Fury (frete de R$ 15,00)\nPor R$ 299,90")
        self.assertIsNone(independente.produto)
        self.assertIn("multiplas_ofertas", independente.motivos)

    def test_kit_com_um_preco_nao_e_multiplos_por_nomear_dois_objetos(self) -> None:
        r = extractor.extrair_detalhado("Kit SSD Kingston + Headset Logitech\nPor R$ 450")
        self.assertEqual(r.produto["preco"], 450)
        self.assertNotIn("multiplas_ofertas", r.motivos)

    def test_derivado_de_cada_linha_e_calculado_uma_vez_por_mensagem(self) -> None:
        texto = "Notebook Dell\nR$ 3500,00\nProcessador: Intel Core i5\nÀ vista R$ 2999,90"
        with patch.object(extractor, "_descricao_linha", wraps=extractor._descricao_linha) as descricao:
            r = extractor.extrair_detalhado(texto)
        self.assertEqual(r.produto["preco"], 2999.9)
        self.assertEqual(descricao.call_count, len(texto.splitlines()))

    def test_clausulas_nao_colam_palavras_dispersas_em_frase_nova(self) -> None:
        regras = preparar_filtros([{"id": 1, "palavras_chave": ["memória ram"]}])
        separadas = avaliar_mensagem("SSD R$ 99 - Memória - oferta - RAM", regras)
        self.assertFalse(separadas.aceita, separadas.diagnostico)
        self.assertIn("palavra_ausente", separadas.diagnostico["por_regra"][0]["motivos"])
        contiguas = avaliar_mensagem("SSD R$ 99 - Memória RAM", regras)
        self.assertTrue(contiguas.aceita, contiguas.diagnostico)


class TestSegundaRetomadaNoPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_veto_multiplos_e_campo_usam_as_mesmas_decisoes_na_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            cliente = ClienteFake()
            repo = RepositorioSupabase(cliente)
            cache = CacheFiltros(repo)
            cache.filtros = [
                {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
                {"id": 2},
            ]
            pipeline = Pipeline(estado, repo, StorageFake(), TelegramFake(), cache,
                                replace(Config(), state_dir=Path(diretorio)))
            try:
                casos = [
                    ("SSD R$ 299,90 - Frete incluso, USADO", "bloqueio_global"),
                    ("SSD R$ 350 / Headset Logitech por R$ 149", "multiplas_ofertas"),
                    ("Notebook Dell\nR$ 3500\nProcessador: Intel Core i5\nÀ vista R$ 2999,90", "aceita_por_regra"),
                ]
                for msg_id, (texto, motivo) in enumerate(casos, 1):
                    await estado.registrar(mensagem(msg_id=msg_id, texto=texto))
                    job = await estado.obter_oferta(time.time(), True)
                    antes = len(cliente.consultas)
                    await pipeline._oferta(job)
                    evento = await estado.evento(job["canal_id"], msg_id)
                    self.assertEqual(json.loads(evento["diagnostico"])["motivo"], motivo)
                    if motivo != "aceita_por_regra":
                        self.assertEqual(evento["estado"], "descartada")
                        self.assertIsNone(evento["decisao"])
                        self.assertEqual(len(cliente.consultas), antes)
                        self.assertIsNone(await estado.obter_oferta(time.time(), True))
                    else:
                        self.assertEqual(evento["estado"], "aprovada")
                        self.assertEqual(json.loads(evento["decisao"])["preco"], 2999.9)
                        self.assertEqual(len(cliente.tabelas["produtos"]), 1)
                        self.assertNotIn("conteudo", cliente.tabelas["produtos"][0])
            finally:
                await pipeline.encerrar()
                await estado.fechar()
