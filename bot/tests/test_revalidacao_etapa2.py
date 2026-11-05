"""Contraprovas sintéticas da revalidação; nenhum canal ou serviço real.

Exigem o PRD aprovado, sem expectedFailure/skip: falhas permanecem visíveis
até a correção de conteúdo, associação de preços e evidência de múltiplos.
"""

import unittest
from unittest.mock import patch

from src.avaliacao import avaliar_mensagem
from src.extractor import extrair_detalhado
from src.filters import preparar_filtros


class TestRevalidacaoEtapa2(unittest.TestCase):
    def setUp(self) -> None:
        rede = patch("socket.socket", side_effect=AssertionError("Rede proibida"))
        rede.start()
        self.addCleanup(rede.stop)

    def test_condicao_apos_frete_incluso_continua_sujeita_ao_veto(self) -> None:
        regras = preparar_filtros([
            {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
            {"id": 2},
        ])
        resultado = avaliar_mensagem("SSD Kingston R$ 299,90 - Frete incluso, USADO", regras)
        self.assertFalse(resultado.aceita, resultado.diagnostico)
        self.assertIn("usado", resultado.extracao.conteudo)
        self.assertEqual(resultado.diagnostico["motivo"], "bloqueio_global")
        self.assertEqual(resultado.diagnostico["regra"], 1)

    def test_produtos_com_precos_proprios_na_mesma_linha_nao_viram_card_unico(self) -> None:
        for precos in (("350,00", "por R$ 149,90"), ("299,90", "R$ 299,90")):
            with self.subTest(precos=precos):
                texto = (f"SSD Kingston R$ {precos[0]} / Headset Logitech {precos[1]}\n"
                         "https://loja.example/ofertas")
                resultado = avaliar_mensagem(texto, preparar_filtros([]))
                self.assertFalse(resultado.aceita, resultado.diagnostico)
                self.assertIsNone(resultado.extracao.produto)
                self.assertIn("multiplas_ofertas", resultado.extracao.motivos)

    def test_campo_processador_do_notebook_nao_e_oferta_independente(self) -> None:
        resultado = extrair_detalhado(
            "Notebook Dell\nR$ 3500,00\nProcessador: Intel Core i5\n"
            "À vista R$ 2999,90\nhttps://loja.example/notebook")
        self.assertIsNotNone(resultado.produto, resultado.motivos)
        self.assertEqual(resultado.produto["titulo"], "Notebook Dell")
        self.assertEqual(resultado.produto["preco"], 2999.9)
        self.assertIn("processador: intel core i5", resultado.conteudo)
        self.assertNotIn("multiplas_ofertas", resultado.motivos)

    def test_controle_multiplos_em_linhas_distintas_continua_ambiguo(self) -> None:
        resultado = extrair_detalhado(
            "SSD Kingston R$ 350,00\nHeadset Logitech por R$ 149,90\nhttps://loja.example/ofertas")
        self.assertIsNone(resultado.produto)
        self.assertIn("multiplas_ofertas", resultado.motivos)

    def test_controle_capacidade_preserva_preco_final_do_unico_produto(self) -> None:
        resultado = extrair_detalhado(
            "SSD Kingston\nR$ 350,00\nCapacidade 1 TB\nÀ vista R$ 299,90\nhttps://loja.example/SSD")
        self.assertIsNotNone(resultado.produto, resultado.motivos)
        self.assertEqual(resultado.produto["preco"], 299.9)
        self.assertIn("capacidade 1 tb", resultado.conteudo)
        self.assertNotIn("multiplas_ofertas", resultado.motivos)
