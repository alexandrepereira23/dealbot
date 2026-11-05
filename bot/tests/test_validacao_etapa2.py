"""Contraprovas sintéticas do PRD etapa 2; sem rede, tokens ou dados reais.

Casos exigem o contrato aprovado e ficam falhando até corrigir as causas no
extrator. Não marcar como expectedFailure nem enfraquecer vetos para obter verde.
"""

import unittest
from unittest.mock import patch

from src.avaliacao import avaliar_mensagem
from src.extractor import extrair_detalhado
from src.filters import preparar_filtros


class TestValidacaoEtapa2(unittest.TestCase):
    def test_condicao_apos_preco_inline_nao_pode_furar_bloqueio_global(self) -> None:
        regras = preparar_filtros([
            {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
            {"id": 2, "preco_max": 350},
        ])
        with patch("socket.socket", side_effect=AssertionError("Rede proibida")):
            resultado = avaliar_mensagem("SSD Kingston R$ 299,90 - USADO", regras)
        self.assertFalse(resultado.aceita, resultado.diagnostico)
        self.assertEqual(resultado.diagnostico["motivo"], "bloqueio_global")
        self.assertIn("usado", resultado.extracao.conteudo)

    def test_modelo_capacidade_e_variante_apos_preco_inline_sao_descritivos(self) -> None:
        resultado = extrair_detalhado("SSD Kingston R$ 299,90 - NV2 1 TB NVMe")
        self.assertIsNotNone(resultado.produto)
        self.assertIn("NV2 1 TB NVMe", resultado.produto["titulo"])
        self.assertIn("nv2 1 tb nvme", resultado.conteudo)

    def test_frete_gratis_com_dois_pontos_nao_e_preco_zero_do_produto(self) -> None:
        regras = preparar_filtros([{"id": 1, "preco_max": 0}])
        resultado = avaliar_mensagem(
            "SSD Kingston\nFrete: grátis\nhttps://loja.example/SSD", regras)
        self.assertIsNotNone(resultado.extracao.produto)
        self.assertIsNone(resultado.extracao.produto["preco"])
        self.assertFalse(resultado.aceita)
        self.assertEqual(resultado.diagnostico["por_regra"][0]["motivos"], ["preco_desconhecido"])
        # Sem link nem preço de produto, só frete gratuito não cria evidência.
        self.assertIsNone(extrair_detalhado("SSD Kingston\nFrete: grátis").produto)

    def test_frete_de_valor_nao_vira_preco_anterior(self) -> None:
        resultado = extrair_detalhado("SSD Kingston\nFrete de R$ 15,00\nhttps://loja.example/SSD")
        self.assertIsNotNone(resultado.produto)
        self.assertIsNone(resultado.produto["preco"])
        self.assertIsNone(resultado.produto["preco_original"])

    def test_especificacao_entre_precos_nao_define_segundo_produto(self) -> None:
        resultado = extrair_detalhado(
            "SSD Kingston\nR$ 350,00\nCapacidade 1 TB\nÀ vista R$ 299,90\nhttps://loja.example/SSD")
        self.assertIsNotNone(resultado.produto, resultado.motivos)
        self.assertEqual(resultado.produto["preco"], 299.9)
        self.assertIn("capacidade 1 tb", resultado.conteudo)
        self.assertNotIn("multiplas_ofertas", resultado.motivos)

    def test_controles_gratuidade_e_multiplos_reais_continuam_distintos(self) -> None:
        gratuito = extrair_detalhado("Jogo de PS5 grátis")
        self.assertEqual(gratuito.produto["preco"], 0)
        simples = extrair_detalhado("SSD Kingston\nR$ 350,00\nÀ vista R$ 299,90\nhttps://loja.example/SSD")
        self.assertEqual(simples.produto["preco"], 299.9)
        multiplos = extrair_detalhado("SSD Kingston R$ 299,90\nHeadset Logitech R$ 149,90")
        self.assertIsNone(multiplos.produto)
        self.assertIn("multiplas_ofertas", multiplos.motivos)
