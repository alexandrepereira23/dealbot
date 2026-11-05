"""Controles sintéticos da retomada VAL-ET2-001/002/003, sem canais reais."""

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

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


class TestCorrecaoEtapa2(unittest.TestCase):
    def test_condicao_inline_em_qualquer_posicao_chega_ao_veto_global(self) -> None:
        regras = preparar_filtros([
            {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado", "recondicionado"]},
            {"id": 2},
        ])
        for texto in (
            "SSD Kingston R$ 299,90 - USADO",
            "SSD Kingston por R$ 299,90 - recondicionado",
            "Por R$ 299,90 - SSD Kingston - USADO",
            "SSD Kingston - R$ 299,90 - Frete grátis - USADO",
            "SSD Kingston - R$ 299,90 / Frete: grátis / USADO",
            "SSD Kingston R$ 299,90 - Frete grátis; USADO",
            "SSD Kingston R$ 299,90 - Frete grátis USADO",
            "SSD Kingston R$ 299,90 - Frete – grátis USADO",
            "SSD Kingston R$ 299,90 - Frete - grátis USADO",
        ):
            with self.subTest(texto=texto):
                resultado = avaliar_mensagem(texto, regras)
                self.assertFalse(resultado.aceita, resultado.diagnostico)
                self.assertEqual(resultado.diagnostico["motivo"], "bloqueio_global")
                self.assertEqual(resultado.diagnostico["regra"], 1)

    def test_cauda_descritiva_mantem_modelo_sem_matching_em_servicos(self) -> None:
        texto = ("SSD Kingston por R$ 299,90 - NV2 1 TB - NVMe / Frete de R$ 15,00\n"
                 "Use o cupom: `USADO`\nEntre no grupo de recondicionado https://t.me/sintetico")
        resultado = extrair_detalhado(texto)
        self.assertIn("NV2 1 TB - NVMe", resultado.produto["titulo"])
        self.assertIn("nv2 1 tb", resultado.conteudo)
        for removido in ("frete", "usado", "recondicionado", "15", "299", "t.me"):
            self.assertNotIn(removido, resultado.conteudo)
        self.assertEqual(resultado.produto["preco"], 299.9)
        self.assertIsNone(resultado.produto["preco_original"])

    def test_cupom_no_mesmo_segmento_nao_apaga_condicao_separada(self) -> None:
        regras = preparar_filtros([
            {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
        ])
        resultado = avaliar_mensagem("SSD R$ 99 - Cupom: USADO - novo", regras)
        self.assertTrue(resultado.aceita)
        self.assertEqual(resultado.extracao.produto["cupom"], "USADO")
        self.assertNotIn("usado", resultado.extracao.conteudo)
        self.assertIn("novo", resultado.extracao.conteudo)

    def test_frete_gratis_com_marcadores_nao_vira_gratuidade(self) -> None:
        regras = preparar_filtros([{"id": 1, "preco_max": 0}])
        for linha in ("Frete: grátis", "Frete:grátis", "Envio = gratuito", "Entrega - gratuita",
                      "Frete de graça", "Grátis de frete", "Frete grátis", "Frete – grátis", "Frete é grátis"):
            with self.subTest(linha=linha):
                resultado = avaliar_mensagem("SSD Kingston\n" + linha + "\nhttps://loja.example/ssd", regras)
                self.assertIsNone(resultado.extracao.produto["preco"])
                self.assertFalse(resultado.aceita)
                self.assertEqual(resultado.diagnostico["por_regra"][0]["motivos"], ["preco_desconhecido"])

    def test_frete_com_de_e_pontuacao_nunca_e_atual_ou_anterior(self) -> None:
        for trecho in ("Frete de R$ 15,00", "Entrega: de R$ 15,00", "Envio de: R$ 15,00",
                       "R$ 15,00 de frete", "Frete por R$ 15,00"):
            with self.subTest(trecho=trecho):
                resultado = extrair_detalhado("SSD Kingston\n" + trecho + "\nhttps://loja.example/ssd")
                self.assertIsNone(resultado.produto["preco"])
                self.assertIsNone(resultado.produto["preco_original"])
                completo = extrair_detalhado("SSD Kingston\nDe R$ 399,90 por R$ 299,90 / " + trecho)
                self.assertEqual((completo.produto["preco"], completo.produto["preco_original"]), (299.9, 399.9))

    def test_gratuidade_real_com_frete_gratis_ou_pago_continua_zero(self) -> None:
        for frete in ("Frete: grátis", "Frete de R$ 15,00", "Frete por R$ 15,00", "Frete – grátis"):
            with self.subTest(frete=frete):
                resultado = extrair_detalhado("Jogo de PS5 grátis\n" + frete)
                self.assertEqual(resultado.produto["preco"], 0)
                self.assertIsNone(resultado.produto["preco_original"])

    def test_especificacoes_entre_precos_preservam_um_produto(self) -> None:
        for especificacao in ("Capacidade 1 TB", "Modelo NV2", "Armazenamento: SSD NVMe 1 TB",
                              "Cor: preta", "Com memória RAM de 16 GB", "NV2 1 TB NVMe"):
            with self.subTest(especificacao=especificacao):
                resultado = extrair_detalhado("SSD Kingston\nR$ 350,00\n" + especificacao +
                                             "\nÀ vista R$ 299,90\nhttps://loja.example/ssd")
                self.assertIsNotNone(resultado.produto, resultado.motivos)
                self.assertEqual(resultado.produto["preco"], 299.9)
                self.assertNotIn("multiplas_ofertas", resultado.motivos)

    def test_especificacao_nao_esconde_segundo_produto_com_preco_proprio(self) -> None:
        for titulo in ("Headset Logitech", "SSD Samsung 1 TB", "Produto B especial", "Logitech Headset G435"):
            with self.subTest(titulo=titulo):
                resultado = extrair_detalhado("SSD Kingston\nR$ 299,90\nCapacidade 1 TB\n" + titulo +
                                             "\nR$ 299,90\nhttps://loja.example/ofertas")
                self.assertIsNone(resultado.produto)
                self.assertIn("multiplas_ofertas", resultado.motivos)

    def test_finais_conflitantes_nao_sao_resolvidos_como_especificacao(self) -> None:
        resultado = extrair_detalhado("SSD Kingston\nPor R$ 350,00\nCapacidade 1 TB\nPor R$ 299,90")
        self.assertIsNone(resultado.produto)
        self.assertIn("preco_ambiguo", resultado.motivos)

    def test_anuncio_de_servico_nao_fabrica_descricao_de_produto(self) -> None:
        for linha in ("Frete de R$ 15,00 para SSD", "Desconto de R$ 50 na compra de SSD",
                      "R$ 50 de desconto acima de R$ 300"):
            with self.subTest(linha=linha):
                self.assertIsNone(extrair_detalhado(linha + "\nhttps://loja.example/promo").produto)

    def test_especificacao_de_memoria_nao_cria_outro_produto_sem_preco_proprio(self) -> None:
        resultado = extrair_detalhado("Notebook Dell\nR$ 3500,00\nMemória RAM 16 GB\nÀ vista R$ 2999,90")
        self.assertIsNotNone(resultado.produto, resultado.motivos)
        self.assertEqual(resultado.produto["preco"], 2999.9)
        self.assertIn("memoria ram 16 gb", resultado.conteudo)
        independente = extrair_detalhado("Notebook Dell R$ 3500\nMemória RAM 16 GB por R$ 299,90")
        self.assertIsNone(independente.produto)
        self.assertIn("multiplas_ofertas", independente.motivos)

    def test_marca_antes_do_segundo_objeto_nao_mistura_preco_e_titulo(self) -> None:
        resultado = extrair_detalhado("SSD Kingston R$ 350,00\nLogitech Headset G435 por R$ 299,90")
        self.assertIsNone(resultado.produto)
        self.assertIn("multiplas_ofertas", resultado.motivos)

    def test_pontuacao_de_parcela_nao_vira_preco_anterior(self) -> None:
        for parcela in ("10x de: R$ 29,90", "Parcela de: R$ 29,90"):
            with self.subTest(parcela=parcela):
                resultado = extrair_detalhado("SSD Kingston\n" + parcela + "\nhttps://loja.example/ssd")
                self.assertIsNone(resultado.produto["preco"])
                self.assertIsNone(resultado.produto["preco_original"])

    def test_servico_inline_nao_apaga_modelo_sem_espaco_antes_de_ponto_virgula(self) -> None:
        for servico in ("Frete grátis;", "Frete – grátis", "Frete - grátis"):
            with self.subTest(servico=servico):
                resultado = extrair_detalhado("SSD Kingston R$ 299,90 - " + servico + " NV2 1 TB NVMe")
                self.assertIn("NV2 1 TB NVMe", resultado.produto["titulo"])
                self.assertIn("nv2 1 tb nvme", resultado.conteudo)

    def test_memoria_com_marca_modelo_e_preco_em_linha_seguinte_e_independente(self) -> None:
        resultado = extrair_detalhado(
            "Notebook Dell R$ 3500\nMemória RAM 16 GB Kingston Fury\nPor R$ 299,90")
        self.assertIsNone(resultado.produto)
        self.assertIn("multiplas_ofertas", resultado.motivos)
        com_links = extrair_detalhado("Notebook Dell R$ 3500\nhttps://loja.example/notebook\n"
            "Memória RAM 16 GB Kingston Fury\nPor R$ 299,90\nhttps://loja.example/memoria")
        self.assertIsNone(com_links.produto)
        self.assertIn("multiplas_ofertas", com_links.motivos)

    def test_memoria_apenas_quantificada_continua_especificacao(self) -> None:
        for campo in ("Memória RAM 16 GB", "Memória RAM 16 GB DDR4"):
            with self.subTest(campo=campo):
                resultado = extrair_detalhado("Notebook Dell R$ 3500\n" + campo + "\nÀ vista R$ 2999,90")
                self.assertIsNotNone(resultado.produto, resultado.motivos)
                self.assertEqual(resultado.produto["preco"], 2999.9)


class TestCorrecaoNoPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_caudas_frete_e_especificacoes_decidem_antes_da_rede(self) -> None:
        """As mesmas mensagens passam pela inbox, regras e projeção de produção."""
        with tempfile.TemporaryDirectory() as diretorio:
            estado = EstadoLocal(Path(diretorio))
            await estado.abrir()
            cliente = ClienteFake()
            repo = RepositorioSupabase(cliente)
            cache = CacheFiltros(repo)
            pipeline = Pipeline(estado, repo, StorageFake(), TelegramFake(), cache,
                                replace(Config(), state_dir=Path(diretorio)))
            try:
                casos = [
                    ("SSD Kingston R$ 299,90 - USADO", [
                        {"id": 1, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado"]},
                        {"id": 2},
                    ], "descartada", "bloqueio_global"),
                    ("SSD Kingston\nFrete: grátis\nhttps://loja.example/SSD",
                     [{"id": 1, "preco_max": 0}], "descartada", "nenhuma_regra_aceitou"),
                    ("SSD Kingston\nR$ 350,00\nCapacidade 1 TB\nÀ vista R$ 299,90\nhttps://loja.example/SSD",
                     [{"id": 1, "palavras_chave": ["ssd", "kingston"], "modo_palavras": "todas", "preco_max": 300}],
                     "aprovada", "aceita_por_regra"),
                ]
                for msg_id, (texto, regras, situacao, motivo) in enumerate(casos, 1):
                    with self.subTest(msg_id=msg_id):
                        cache.filtros = regras
                        await estado.registrar(mensagem(msg_id=msg_id, texto=texto))
                        job = await estado.obter_oferta(time.time(), True)
                        antes = len(cliente.consultas)
                        await pipeline._oferta(job)
                        evento = await estado.evento(job["canal_id"], msg_id)
                        diagnostico = json.loads(evento["diagnostico"])
                        self.assertEqual(evento["estado"], situacao)
                        self.assertEqual(diagnostico["motivo"], motivo)
                        if situacao == "descartada":
                            self.assertEqual(len(cliente.consultas), antes, "Rejeição não chama repositório remoto")
                            self.assertIsNone(evento["decisao"])
                            if msg_id == 2:
                                self.assertEqual(diagnostico["por_regra"][0]["motivos"], ["preco_desconhecido"])
                        else:
                            self.assertEqual(json.loads(evento["decisao"])["preco"], 299.9)
                            self.assertEqual(len(cliente.tabelas["produtos"]), 1)
                            self.assertNotIn("diagnostico", cliente.tabelas["produtos"][0])
            finally:
                await pipeline.encerrar()
                await estado.fechar()
