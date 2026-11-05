"""Fixtures sintéticas; sem credenciais, SDK conectado ou acesso à rede."""

import asyncio
import json
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from src.adaptadores import ADAPTADORES_POR_ID, ADAPTADORES_POR_USERNAME, selecionar_adaptador
from src.dinheiro import em_centavos, numero_publico
from src.extractor import extrair_detalhado, extrair_produto
from src.normalizacao import contem_termo, normalizar_texto


class NormalizacaoTests(unittest.TestCase):
    def test_unicode_acentos_caixa_e_espacos(self):
        self.assertEqual(normalizar_texto("  MEMÓRIA\u00a0 RAM\n Árvore Straße 東京 "), "memoria ram arvore straße 東京")

    def test_limites_de_palavras_e_frases(self):
        for texto, termo, esperado in [
            ("memoria ram 16 gb", "memoria ram", True),
            ("memoria oferta ram", "memoria ram", False),
            ("gamer programa hdtv epcot", "game", False),
            ("programa", "ram", False), ("hdtv", "tv", False),
            ("epcot", "pc", False), ("ssd 東京ssd", "ssd", True),
            ("東京ssd", "ssd", False), ("memoria ram", "", False),
        ]:
            with self.subTest(texto=texto, termo=termo):
                self.assertEqual(contem_termo(texto, termo), esperado)


class DinheiroTests(unittest.TestCase):
    def test_centavos_exatos_e_numeros_publicos(self):
        for valor, centavos in [(0, 0), (299.9, 29990), ("299.90", 29990),
                                 (Decimal("299.90"), 29990), (99999999.99, 9999999999),
                                 (Decimal("0.10"), 10), ("0.01", 1)]:
            with self.subTest(valor=valor):
                self.assertEqual(em_centavos(valor), centavos)
                self.assertEqual(em_centavos(numero_publico(centavos)), centavos)
                json.dumps(numero_publico(centavos), allow_nan=False)
        self.assertIsNone(numero_publico(None))

    def test_rejeita_precisao_locale_faixa_e_nao_finitos(self):
        for valor in [True, None, -1, "-1", "R$ 1,00", "1,00", "1.234", "1e2", " 1.00 ",
                      0.001, 0.1 + 0.2, 100000000, float("inf"), float("nan"),
                      Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01"),
                      Decimal("0.99999999999999999999999999999"), Decimal("1e-1000000")]:
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                em_centavos(valor)

    def test_centavos_publicos_invalidos(self):
        for valor in [-1, 1.5, True, 10000000000]:
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                numero_publico(valor)


class ExtracaoTests(unittest.TestCase):
    def oferta(self, trecho, descricao="SSD Kingston NV2 1 TB", **kwargs):
        return extrair_detalhado(f"{descricao}\n{trecho}\nhttps://loja.example/SSD", **kwargs)

    def test_corpus_sintetico_sem_rede(self):
        corpus = json.loads((Path(__file__).parent / "fixtures/extracao_sintetica.json").read_text(encoding="utf-8"))
        with patch("socket.socket", side_effect=AssertionError("rede proibida")):
            for caso in corpus["casos"]:
                texto = caso["texto"] + caso.get("repetir", "") * caso.get("vezes", 0)
                with self.subTest(caso=caso["id"]):
                    resultado = extrair_detalhado(texto, caso.get("contexto"))
                    json.dumps(resultado.produto, allow_nan=False)
                    self.assertIsInstance(resultado.motivos, tuple)

    def test_entrada_adversarial_sem_backtracking_de_espacos(self):
        for prefixo in ["R$", "por", "cupom"]:
            with self.subTest(prefixo=prefixo):
                resultado = self.oferta(prefixo + " " * 32768 + "?")
                self.assertIsNone(resultado.produto["preco"])
                self.assertIsNone(resultado.produto["cupom"])

    def test_chamada_repetida_nao_tem_regex_aninhada(self):
        resultado = self.oferta("Por R$ 299,90", "oferta " * 4096 + "SSD Kingston NV2")
        self.assertIn("ssd kingston nv2", resultado.conteudo)

    def test_titulo_generico_e_hifens_preservados(self):
        resultado = self.oferta("Por R$ 299,90", "OFERTA IMPERDÍVEL\n🔥 **SSD Kingston - NV2 1 TB - NVMe**")
        self.assertEqual(resultado.produto["titulo"], "SSD Kingston - NV2 1 TB - NVMe")
        self.assertIn("ssd kingston", resultado.conteudo)
        self.assertNotIn("oferta imperdivel", resultado.conteudo)
        longa = "SSD Kingston - " + "variante descritiva " * 12 + "NV2 1 TB - NVMe"
        self.assertEqual(self.oferta("Por R$ 299,90", longa).produto["titulo"], longa)

    def test_preco_no_inicio_nao_apaga_cauda_descritiva(self):
        resultado = extrair_detalhado("Por R$ 299,90 - SSD Kingston NV2 1 TB\nhttps://loja.test/SSD")
        self.assertEqual(resultado.produto["titulo"], "SSD Kingston NV2 1 TB")
        self.assertEqual(resultado.produto["preco"], 299.9)
        self.assertIn("ssd kingston nv2", resultado.conteudo)

    def test_oferta_curta_zero_e_sem_preco(self):
        self.assertEqual(extrair_detalhado("SSD R$ 99").produto["preco"], 99)
        self.assertEqual(extrair_detalhado("SSD R$ 0").produto["preco"], 0)
        self.assertEqual(extrair_detalhado("Jogo de PS5 grátis").produto["preco"], 0)
        self.assertIsNone(self.oferta("", "Notebook RTX 4060 1 TB").produto["preco"])
        self.assertIsNone(extrair_detalhado("Notebook RTX 4060 1 TB").produto)

    def test_sem_produto_divulgacao_desconto_e_modelos(self):
        for texto in ["", "OFERTA IMPERDÍVEL\nhttps://t.me/grupo", "Entre no grupo https://t.me/grupo",
                      "R$ 50 de desconto acima de R$ 300", "20% OFF", "RTX 4060 1 TB", "R$ 99",
                      "OFERTA IMPERDÍVEL R$ 99", "Promoção R$ 99 https://loja.example/promo"]:
            with self.subTest(texto=texto):
                resultado = extrair_detalhado(texto)
                self.assertIsNone(resultado.produto)
                self.assertIn("sem_evidencia_de_oferta", resultado.motivos)

    def test_de_por_frete_e_anterior(self):
        for trecho, atual, anterior in [
            ("De R$ 399,90 por R$ 299,90", 299.9, 399.9),
            ("Por R$ 299,90 / Frete R$ 15,00", 299.9, None),
            ("Frete R$ 15,00\nPor R$ 299,90", 299.9, None),
            ("Antes R$ 399,90\nAgora R$ 299,90", 299.9, 399.9),
            ("R$ 350\nÀ vista R$ 299,90", 299.9, None),
        ]:
            with self.subTest(trecho=trecho):
                produto = self.oferta(trecho).produto
                self.assertIsNotNone(produto)
                self.assertEqual((produto["preco"], produto["preco_original"]), (atual, anterior))

    def test_parcelas_nao_sao_total(self):
        for trecho, esperado in [("10x de R$ 99,90 / à vista R$ 899,00", 899),
                                 ("10x de R$ 99,90 sem juros", None),
                                 ("10 x de R$ 99,90 com juros", None),
                                 ("Parcela de R$ 99,90", None)]:
            with self.subTest(trecho=trecho):
                resultado = self.oferta(trecho)
                self.assertEqual(resultado.produto["preco"], esperado)

    def test_desconto_minimo_nao_sao_precos(self):
        for trecho in ["R$ 50 de desconto acima de R$ 300", "Desconto de R$ 50\nCompra mínima de R$ 300",
                       "Economize R$ 50\n20% OFF", "Cashback R$ 10\nFrete R$ 15"]:
            with self.subTest(trecho=trecho):
                resultado = self.oferta(trecho)
                self.assertIsNone(resultado.produto["preco"])
                self.assertIsNone(resultado.produto["preco_original"])

    def test_formatos_brasileiros_precisos(self):
        for trecho, esperado in [("R$ 1.234,56", 1234.56), ("R$ 299,90", 299.9), ("R$ 299", 299),
                                 ("R$ 1.234", 1234), ("R$\u00a01.234,56", 1234.56),
                                 ("Por 299,90", 299.9), ("R$ 99.999.999,99", 99999999.99)]:
            with self.subTest(trecho=trecho):
                self.assertEqual(self.oferta(trecho).produto["preco"], esperado)

    def test_ambiguidades_nao_arredondam(self):
        for trecho in ["R$ 1,234", "R$ 12.34", "R$ 1.23.456", "R$ 1.234.56,789", "R$ -10"]:
            with self.subTest(trecho=trecho):
                resultado = self.oferta(trecho)
                self.assertIsNone(resultado.produto["preco"])
                self.assertIn("formato_preco_ambiguo", resultado.motivos)
        resultado = self.oferta("R$ 100.000.000,00")
        self.assertIsNone(resultado.produto["preco"])
        self.assertIn("preco_fora_da_faixa", resultado.motivos)

    def test_anterior_inconsistente_nao_inverte_valores(self):
        for anterior in ["199,90", "299,90"]:
            resultado = self.oferta(f"De R$ {anterior} por R$ 299,90")
            self.assertEqual(resultado.produto["preco"], 299.9)
            self.assertIsNone(resultado.produto["preco_original"])
            self.assertIn("preco_anterior_inconsistente", resultado.motivos)

    def test_multiplos_produtos_e_finais_conflitantes(self):
        for texto in ["SSD R$ 299,90\nHeadset R$ 149,90", "SSD R$ 299,90\nHeadset R$ 299,90",
                      "SSD Kingston\nPor R$ 99\nHeadset Logitech\nPor R$ 99",
                      "SSD\nPor R$ 299,90 / Por R$ 149,90", "SSD\nR$ 299,90 / R$ 149,90"]:
            with self.subTest(texto=texto):
                resultado = extrair_detalhado(texto)
                self.assertIsNone(resultado.produto)
                self.assertTrue({"multiplas_ofertas", "preco_ambiguo"}.intersection(resultado.motivos))

    def test_frete_gratis_nao_significa_produto_gratis(self):
        for trecho in ["Frete grátis", "R$ 0 de frete", "Cupom de R$ 50"]:
            with self.subTest(trecho=trecho):
                self.assertIsNone(self.oferta(trecho).produto["preco"])

    def test_link_comercial_acima_de_social_preserva_caracteres(self):
        url = "https://Loja.example/Produto(A)?Cupom=AbC&x=1#Detalhe"
        resultado = extrair_detalhado(f"Entre no grupo https://t.me/grupo\nSSD R$ 99\n({url})")
        self.assertEqual(resultado.produto["link"], url)
        self.assertEqual(resultado.fonte_link, "texto")

    def test_estrelas_na_url_so_saem_com_delimitador_externo(self):
        for entrada, esperado in [("https://loja.example/A?x=**", "https://loja.example/A?x=**"),
                                   ("**https://loja.example/A**", "https://loja.example/A")]:
            with self.subTest(entrada=entrada):
                self.assertEqual(extrair_detalhado("SSD R$ 99\n" + entrada).produto["link"], esperado)

    def test_delimitadores_externos_nao_removem_caracteres_legitimos(self):
        for entrada, esperado in [
            ("https://loja.example/A?x=)", "https://loja.example/A?x=)"),
            ("(https://loja.example/A?x=))", "https://loja.example/A?x=)"),
            ("https://loja.example/A?x='Y'", "https://loja.example/A?x='Y'"),
            ("'https://loja.example/A'", "https://loja.example/A"),
        ]:
            with self.subTest(entrada=entrada):
                self.assertEqual(extrair_detalhado("SSD R$ 99\n" + entrada).produto["link"], esperado)

    def test_links_invalidos_e_social_nao_servem_de_evidencia(self):
        for url in ["javascript:alert(1)", "ftp://loja.example/a", "https:///nada", "https://bad_host.example/a",
                    "https://loja.example:99999/a", "https://t.me/grupo", "https://www.instagram.com/a"]:
            with self.subTest(url=url):
                self.assertIsNone(extrair_detalhado(f"Notebook Modelo\n{url}").produto)

    def test_entidades_botoes_e_offsets_python_apos_emoji(self):
        texto = "🔥 SSD Kingston\nComprar"
        contexto = {"versao": 1, "links": [{"url": "https://curto.example/AbC", "origem": "entidade",
                     "rotulo": "Comprar", "offset": texto.index("Comprar"), "length": 7}]}
        resultado = extrair_detalhado(texto, contexto)
        self.assertEqual(resultado.produto["link"], "https://curto.example/AbC")
        self.assertEqual(resultado.produto["titulo"], "SSD Kingston")
        self.assertNotIn("comprar", resultado.conteudo)
        self.assertEqual(resultado.fonte_link, "entidade")
        contexto["links"][0] = {"url": "https://curto.example/AbC", "origem": "botao", "rotulo": "Comprar"}
        self.assertEqual(extrair_detalhado(texto, contexto).produto, resultado.produto)

    def test_conteudo_sem_url_codigo_rodape_mas_com_descricao_final(self):
        resultado = self.oferta("R$ 299,90\nUse o cupom: `Recondicionado`\nEntre no grupo SSD usado\nMemória RAM nova")
        self.assertIn("memoria ram nova", resultado.conteudo)
        self.assertNotIn("recondicionado", resultado.conteudo)
        self.assertNotIn("usado", resultado.conteudo)
        self.assertNotIn("example", resultado.conteudo)

    def test_cupom_contextual_preserva_caixa(self):
        for trecho in ["Use o cupom: `AbC123`", "cupom AbC123", "CUPOM: **AbC123**"]:
            with self.subTest(trecho=trecho):
                self.assertEqual(self.oferta("R$ 99\n" + trecho).produto["cupom"], "AbC123")

    def test_cupom_incompleto_isolado_ou_ambiguo(self):
        for trecho in ["`AbC123`", "cupom:", "cupom: DESCONTO", "cupom ABC123\ncupom DEF456"]:
            with self.subTest(trecho=trecho):
                self.assertIsNone(self.oferta("R$ 99\n" + trecho).produto["cupom"])
        self.assertIn("cupom_ambiguo", self.oferta("R$ 99\ncupom ABC123\ncupom DEF456").motivos)

    def test_cupom_incompleto_nao_consume_proxima_linha(self):
        resultado = extrair_detalhado("Cupom:\nNotebook Modelo\nR$ 99")
        self.assertIsNone(resultado.produto["cupom"])
        self.assertEqual(resultado.produto["titulo"], "Notebook Modelo")

    def test_linhas_de_servico_nao_fabricam_produto(self):
        for linha in ["Agora R$ 99", "Desconto de R$ 50", "Compra mínima de R$ 300", "Economize R$ 50"]:
            with self.subTest(linha=linha):
                resultado = extrair_detalhado(linha + "\nhttps://loja.example/desconto")
                self.assertIsNone(resultado.produto)

    def test_cupom_instrucao_nao_vira_conteudo(self):
        resultado = self.oferta("R$ 99\nUse o cupom: `AbC123`")
        self.assertNotIn("use", resultado.conteudo)

    def test_codigo_e_exclusao_raw_nao_entram_no_matching(self):
        texto = "SSD Kingston\nR$ 99\nCupom: USADO\nRODAPE"
        contexto = {"codigos": [{"offset": texto.index("USADO"), "length": 5}],
                    "exclusoes": [{"offset": texto.index("RODAPE"), "length": 6}]}
        resultado = extrair_detalhado(texto, contexto)
        self.assertNotIn("usado", resultado.conteudo)
        self.assertNotIn("rodape", resultado.conteudo)
        self.assertEqual(resultado.produto["cupom"], "USADO")

    def test_formatacao_de_codigo_descritiva_nao_apaga_produto_modelo_ou_condicao(self):
        for texto, contexto in [
            ("`SSD Kingston NV2 1 TB`\nR$ 299,90\n`USADO`", {}),
            ("SSD Kingston NV2 1 TB\nR$ 299,90\nUSADO", {"codigos": [{"offset": 0, "length": 20}, {"offset": 32, "length": 5}]}),
        ]:
            with self.subTest(texto=texto):
                resultado = extrair_detalhado(texto, contexto)
                self.assertIn("SSD Kingston NV2 1 TB", resultado.produto["titulo"])
                self.assertIn("usado", resultado.conteudo)
                self.assertIsNone(resultado.produto["cupom"])

    def test_categorias_objeto_principal_e_sem_substrings(self):
        for descricao, categoria in [("Cadeira gamer", "casa"), ("Headset gamer", "eletronicos"),
                                      ("Jogo de PS5", "games"), ("Programa gamer", "outros"),
                                      ("Produto epcot hdtv", "outros"), ("Memória RAM", "eletronicos"),
                                      ("Camiseta PC gamer", "moda"), ("Camisa PC gamer", "moda")]:
            with self.subTest(descricao=descricao):
                self.assertEqual(self.oferta("R$ 99", descricao).produto["categoria"], categoria)

    def test_wrapper_e_produto_somente_publico(self):
        texto = "SSD Kingston\nR$ 99\nhttps://loja.example/SSD"
        resultado = extrair_detalhado(texto)
        self.assertEqual(asyncio.run(extrair_produto(texto)), resultado.produto)
        self.assertEqual(set(resultado.produto), {"titulo", "preco", "preco_original", "cupom", "link", "categoria"})

    def test_fallback_adaptadores_sem_canais_inventados(self):
        self.assertEqual(ADAPTADORES_POR_ID, {})
        self.assertEqual(ADAPTADORES_POR_USERNAME, {})
        adaptador = lambda texto, contexto: (texto, contexto)
        with patch.dict(ADAPTADORES_POR_USERNAME, {"sintetico": adaptador}):
            self.assertIs(selecionar_adaptador(None, " @SINTETICO "), adaptador)
        self.assertIsNone(selecionar_adaptador(-123, "desconhecido"))
