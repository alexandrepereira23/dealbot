"""Regressões sintéticas da revisão: descrição e frete, sem rede."""

import unittest

from src.avaliacao import avaliar_mensagem
from src.filters import preparar_filtros
from src.normalizacao import contem_termo


REGRAS = [
    {"id": 1, "tipo_regra": "bloqueio_global",
     "palavras_bloqueio": ["usado", "recondicionado"]},
    {"id": 2, "palavras_chave": ["SSD", "Kingston"],
     "modo_palavras": "todas", "preco_max": 350},
]
FILTROS = preparar_filtros(REGRAS)
TITULO = "SSD Kingston NV2 1 TB"
LINK = "https://loja.example/ssd"


class TestReproducoesRevisaoEtapa2(unittest.TestCase):
    def conferir(self, linha: str, aceita: bool, motivo: str) -> None:
        resultado = avaliar_mensagem(f"{TITULO}\n{linha}\n{LINK}", FILTROS)
        produto = resultado.extracao.produto or {}
        self.assertEqual(
            (resultado.aceita, resultado.diagnostico["motivo"],
             produto.get("preco"), produto.get("preco_original")),
            (aceita, motivo, 299.9, None),
        )
        self.assertEqual(resultado.diagnostico["regra"], 2 if aceita else 1)

    def test_recondicionado_apos_pix(self) -> None:
        self.conferir("Por R$ 299,90 no Pix (RECONDICIONADO)", False, "bloqueio_global")

    def test_usado_apos_a_vista(self) -> None:
        self.conferir("R$ 299,90 à vista USADO", False, "bloqueio_global")

    def test_frete_com_destino(self) -> None:
        self.conferir("R$ 299,90\nFrete para Goiânia R$ 15,00", True, "aceita_por_regra")

    def test_pagamento_preserva_condicoes_e_novos_em_variantes(self) -> None:
        for pagamento in ("no Pix", "NO PIX", "à vista", "a VISTA", "À VISTA:"):
            for condicao in ("USADO", "(Recondicionado)", "[usádo]", "NOVO"):
                for prefixo, separador in ((TITULO + " ", " "), (TITULO + "\n", " "),
                                           (TITULO + "\n", "\n")):
                    with self.subTest(pagamento=pagamento, condicao=condicao,
                                      prefixo=prefixo, separador=separador):
                        texto = f"{prefixo}R$ 299,90{separador}{pagamento} {condicao}\n{LINK}"
                        resultado = avaliar_mensagem(texto, FILTROS)
                        novo = condicao == "NOVO"
                        self.assertEqual(resultado.aceita, novo, resultado.diagnostico)
                        self.assertEqual(resultado.diagnostico["motivo"],
                                         "aceita_por_regra" if novo else "bloqueio_global")
                        self.assertEqual(resultado.extracao.produto["preco"], 299.9)
                        self.assertTrue(contem_termo(resultado.extracao.conteudo,
                                                   "novo" if novo else (
                                                       "recondicionado" if "Recondicionado" in condicao else "usado")))

    def test_pontuacao_nao_apaga_condicao_apos_pagamento(self) -> None:
        for cauda in ("no Pix (USADO)", "à vista: USADO", "NO PIX,usado",
                      "a vista; recondicionado", "no Pix - USADO", "à vista / USADO"):
            with self.subTest(cauda=cauda):
                self.conferir("R$ 299,90 " + cauda, False, "bloqueio_global")

    def test_pagamento_nao_apaga_outros_termos_de_interesse(self) -> None:
        filtros = preparar_filtros([REGRAS[0], {**REGRAS[1], "palavras_chave": ["SSD", "NVMe"]}])
        for pagamento in ("no Pix", "à vista", "a vista"):
            for separador in (" ", "\n"):
                with self.subTest(pagamento=pagamento, separador=separador):
                    resultado = avaliar_mensagem(
                        f"{TITULO}\nR$ 299,90{separador}{pagamento} NVMe novo\n{LINK}", filtros)
                    self.assertTrue(resultado.aceita, resultado.diagnostico)
                    self.assertIn("nvme novo", resultado.extracao.conteudo)

    def test_urls_cupons_rodapes_continuam_excluidos(self) -> None:
        for extra in ("https://loja.example/USADO?condicao=recondicionado",
                      "Cupom: USADO", "Use o cupom: `RECONDICIONADO`",
                      "Entre no grupo de usado e recondicionado https://t.me/sintetico"):
            with self.subTest(extra=extra):
                texto = f"{TITULO}\nR$ 299,90 no Pix NOVO\n{extra}\n{LINK}"
                resultado = avaliar_mensagem(texto, FILTROS)
                self.assertTrue(resultado.aceita, resultado.diagnostico)
                self.assertEqual(resultado.diagnostico["motivo"], "aceita_por_regra")
                self.assertNotIn("usado", resultado.extracao.conteudo)
                self.assertNotIn("recondicionado", resultado.extracao.conteudo)
                bloqueada = avaliar_mensagem(texto.replace("NOVO", "USADO"), FILTROS)
                self.assertFalse(bloqueada.aceita)
                self.assertEqual(bloqueada.diagnostico["motivo"], "bloqueio_global")

    def test_rodape_residual_apos_pagamento_nao_vira_condicao(self) -> None:
        for pagamento in ("no Pix", "à vista"):
            for abertura, fechamento in (("", ""), ("(", ")"), ("[", "]"), ("{", "}")):
                with self.subTest(pagamento=pagamento, abertura=abertura):
                    self.conferir(f"R$ 299,90 {pagamento} {abertura}Entre no grupo de USADO "
                                  f"https://t.me/sintetico{fechamento}", True, "aceita_por_regra")

    def test_frete_destinos_valores_e_limites_de_clausula(self) -> None:
        for frete in ("Frete para Goiânia R$ 15,00", "Envio para São José dos Campos: R$ 450,00",
                      "Entrega em Belo Horizonte R$ 15,00", "FRETE PARA Belém: R$ 450,00",
                      "Envio para Xique-Xique R$ 15,00", "Entrega em Olho d'Água R$ 15,00"):
            for separador in ("\n", " / ", "; ", " | ", ", ", " - "):
                with self.subTest(frete=frete, separador=separador):
                    self.conferir("R$ 299,90" + separador + frete, True, "aceita_por_regra")

    def test_valor_somente_de_frete_nao_e_preco_do_produto(self) -> None:
        for frete in ("Frete para Goiânia R$ 15,00", "Envio para Recife: R$ 450,00",
                      "Entrega em Manaus R$ 0,00", "Frete grátis"):
            with self.subTest(frete=frete):
                resultado = avaliar_mensagem(f"{TITULO}\n{frete}\n{LINK}", FILTROS)
                self.assertIsNotNone(resultado.extracao.produto)
                self.assertIsNone(resultado.extracao.produto["preco"])
                self.assertIsNone(resultado.extracao.produto["preco_original"])
                self.assertFalse(resultado.aceita)
                self.assertEqual(resultado.diagnostico["motivo"], "nenhuma_regra_aceitou")
                self.assertEqual(resultado.diagnostico["por_regra"][-1]["motivos"], ["preco_desconhecido"])

    def test_frete_nao_compete_com_outros_papeis_monetarios(self) -> None:
        for linha in ("R$ 299,90 / Frete grátis", "De R$ 399,90 por R$ 299,90",
                      "R$ 320,00 / Preço final R$ 299,90", "R$ 299,90 / 10x de R$ 29,99",
                      "R$ 299,90 / Desconto de R$ 50 / Compra mínima de R$ 500"):
            with self.subTest(linha=linha):
                resultado = avaliar_mensagem(
                    f"{TITULO}\n{linha}\nEntrega em Porto Alegre R$ 450,00\n{LINK}", FILTROS)
                self.assertTrue(resultado.aceita, resultado.diagnostico)
                self.assertEqual(resultado.extracao.produto["preco"], 299.9)
                self.assertEqual(resultado.extracao.produto["preco_original"],
                                 399.9 if linha.startswith("De ") else None)

    def test_frete_nao_captura_preco_de_outro_produto_ou_clausula(self) -> None:
        for separador in ("\n", " / ", "; ", " | ", ", ", " - "):
            with self.subTest(separador=separador):
                texto = (f"{TITULO} R$ 299,90{separador}Frete para Goiânia R$ 15,00"
                         f"{separador}Headset Logitech R$ 149,90\n{LINK}")
                resultado = avaliar_mensagem(texto, FILTROS)
                self.assertFalse(resultado.aceita)
                self.assertIsNone(resultado.extracao.produto)
                self.assertEqual(resultado.diagnostico["motivo"], "multiplas_ofertas")
        for cauda in ("Frete para Goiânia / R$ 149,90", "Frete para Goiânia; R$ 149,90",
                      "Frete para Goiânia\nR$ 149,90", "Frete para Goiânia Headset R$ 149,90",
                      "Envio para Recife Produto B R$ 149,90",
                      "Frete para Goiânia Impressora Epson R$ 149,90",
                      "Entrega em Goiânia Airfryer Mondial R$ 149,90"):
            with self.subTest(cauda=cauda):
                resultado = avaliar_mensagem(f"{TITULO}\nR$ 299,90\n{cauda}\n{LINK}", FILTROS)
                self.assertFalse(resultado.aceita)
                self.assertIsNone(resultado.extracao.produto)
                self.assertEqual(resultado.diagnostico["motivo"], "preco_ambiguo")

    def test_final_explicito_apos_destino_mantem_precedencia(self) -> None:
        resultado = avaliar_mensagem(
            f"{TITULO}\nR$ 320,00\nFrete para Goiânia preço final R$ 299,90\n{LINK}", FILTROS)
        self.assertTrue(resultado.aceita, resultado.diagnostico)
        self.assertEqual(resultado.extracao.produto["preco"], 299.9)
        self.assertEqual(resultado.extracao.fonte_preco, "final_explicito")
