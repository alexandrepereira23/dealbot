"""Regras sintéticas: sem rede, banco ou configuração de produção."""

import math
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.cache import CacheFiltros
from src.filters import avaliar_produto, passa_no_filtro, preparar_filtros


def produto(**campos: object) -> dict:
    return {"titulo": "SSD Kingston NV2", "categoria": "eletronicos", "preco": 299.9, **campos}


def interesse(**campos: object) -> dict:
    return {"id": 1, "palavras_chave": ["ssd", "kingston"], "modo_palavras": "todas", **campos}


def global_(**campos: object) -> dict:
    return {"id": 2, "tipo_regra": "bloqueio_global", "palavras_bloqueio": ["usado", "recondicionado"], **campos}


class TestFiltrosEtapa2(unittest.TestCase):
    def test_qualquer_todas_e_regras_alternativas(self) -> None:
        self.assertTrue(passa_no_filtro(produto(), [interesse(preco_max=350)]))
        self.assertFalse(passa_no_filtro(produto(titulo="Kingston"), [interesse()]))
        self.assertTrue(passa_no_filtro(produto(titulo="Kingston"), [interesse(modo_palavras="qualquer")]))
        self.assertTrue(passa_no_filtro(produto(titulo="Kingston"), [interesse(), {"id": 3}]))

    def test_descricao_completa_sem_depender_titulo(self) -> None:
        resultado = avaliar_produto(produto(titulo="NV2"), [interesse()], conteudo="ssd kingston nv2 1 tb")
        self.assertTrue(resultado.aceita)
        self.assertEqual(resultado.motivo, "aceita_por_regra")
        self.assertEqual(resultado.regra, 1)

    def test_frases_acentos_caixa_espacos_e_limites(self) -> None:
        regra = [{"palavras_chave": ["memória RAM"]}]
        self.assertTrue(passa_no_filtro(produto(titulo="MEMORIA\u00a0  RAM 16 GB"), regra))
        self.assertFalse(passa_no_filtro(produto(titulo="memoria oferta ram"), regra))
        for termo, titulo in [("pc", "opcao"), ("ram", "programa"), ("hd", "fullhd"), ("tv", "tvs"), ("game", "gamer")]:
            with self.subTest(termo=termo):
                self.assertFalse(passa_no_filtro(produto(titulo=titulo), [{"palavras_chave": [termo]}]))

    def test_condicoes_combinadas_e_motivos_por_regra(self) -> None:
        resultado = avaliar_produto(produto(titulo="Mouse", preco=400), [
            interesse(preco_max=350, categoria="casa"), {"id": 3, "palavras_bloqueio": ["mouse"]},
        ])
        self.assertFalse(resultado.aceita)
        self.assertEqual(resultado.motivo, "nenhuma_regra_aceitou")
        self.assertIsNone(resultado.regra)
        self.assertEqual(resultado.por_regra[0]["regra"], 1)
        self.assertEqual(set(resultado.por_regra[0]["motivos"]), {
            "palavra_ausente", "categoria_divergente", "preco_acima_do_limite",
        })
        self.assertEqual(resultado.por_regra[1]["motivos"], ["bloqueio_da_regra"])

    def test_preco_desconhecido_zero_e_limite_centavo(self) -> None:
        resultado = avaliar_produto(produto(preco=None), [{"id": 1, "preco_max": 350}])
        self.assertFalse(resultado.aceita)
        self.assertEqual(resultado.por_regra[0]["motivos"], ["preco_desconhecido"])
        self.assertTrue(passa_no_filtro(produto(preco=None), [{"preco_max": 350}, {}]))
        self.assertTrue(passa_no_filtro(produto(preco=0), [{"preco_max": 0}]))
        self.assertFalse(passa_no_filtro(produto(preco=None), [{"preco_max": 0}]))
        self.assertFalse(passa_no_filtro(produto(preco=0.01), [{"preco_max": 0}]))
        self.assertTrue(passa_no_filtro(produto(preco=299.9), [{"preco_max": 299.90}]))
        self.assertFalse(passa_no_filtro(produto(preco=299.91), [{"preco_max": 299.9}]))
        self.assertTrue(passa_no_filtro(produto(preco=99999999.99), [{"preco_max": "99999999.99"}]))

    def test_global_veta_antes_de_interesses_e_nunca_autoriza(self) -> None:
        resultado = avaliar_produto(produto(titulo="SSD Kingston recondicionado"), [interesse(), {}, global_()])
        self.assertFalse(resultado.aceita)
        self.assertEqual(resultado.motivo, "bloqueio_global")
        self.assertEqual(resultado.regra, 2)
        self.assertTrue(passa_no_filtro(produto(), [global_()]))
        self.assertFalse(passa_no_filtro(produto(titulo="mouse"), [global_(), interesse()]))

    def test_global_todas_e_bloqueio_local_independente_modo(self) -> None:
        self.assertTrue(passa_no_filtro(produto(titulo="SSD usado"), [global_(modo_palavras="todas")]))
        self.assertFalse(passa_no_filtro(produto(titulo="SSD usado recondicionado"), [global_(modo_palavras="todas")]))
        local = interesse(palavras_bloqueio=["usado", "recondicionado"])
        self.assertFalse(passa_no_filtro(produto(titulo="SSD Kingston usado"), [local]))
        self.assertTrue(passa_no_filtro(produto(titulo="SSD Kingston usado"), [local, {}]))

    def test_vazio_legado_ativo_e_lista_de_palavras_vazia(self) -> None:
        self.assertTrue(passa_no_filtro(produto(), []))
        self.assertTrue(passa_no_filtro(produto(), [{"ativo": False, "palavras_chave": ["ausente"]}]))
        self.assertTrue(passa_no_filtro(produto(), [{"palavras_chave": []}]))
        self.assertTrue(passa_no_filtro(produto(titulo="Kingston"), [{"palavras_chave": ["ssd", "kingston"]}]))

    def test_snapshot_validado_por_completo_sem_fallback_permissivo(self) -> None:
        invalidas = [
            None, {}, [None], [{"tipo_regra": "novo"}], [{"modo_palavras": "talvez"}],
            [{"categoria": "todos"}], [{"categoria": "inventada"}], [{"ativo": "false"}],
            [{"palavras_chave": [""]}], [{"palavras_chave": ["á", "A"]}],
            [{"palavras_chave": ["x" * 101]}], [{"palavras_chave": [str(i) for i in range(51)]}],
            [{"palavras_bloqueio": [123]}], [{"preco_max": -1}], [{"preco_max": math.nan}],
            [{"preco_max": math.inf}], [{"preco_max": True}], [{"preco_max": 1.001}],
            [{"preco_max": 100000000}], [global_(palavras_bloqueio=[])],
            [global_(categoria="casa")], [global_(palavras_chave=["ssd"])], [global_(preco_max=0)],
        ]
        for regras in invalidas:
            with self.subTest(regras=regras), self.assertRaises(ValueError):
                preparar_filtros(regras)

    def test_preparado_reutilizavel_e_diagnostico_sem_termos(self) -> None:
        preparado = preparar_filtros([interesse(palavras_bloqueio=["privado"])])
        resultado = avaliar_produto(produto(), preparado)
        self.assertTrue(resultado.aceita)
        self.assertNotIn("privado", str(resultado.como_dict()))
        self.assertEqual(preparado, preparar_filtros([interesse(palavras_bloqueio=["privado"])]))


class TestCacheEtapa2(unittest.IsolatedAsyncioTestCase):
    async def test_config_invalida_preserva_snapshot_preparado_e_versao(self) -> None:
        repo = SimpleNamespace(carregar_filtros=AsyncMock(return_value=[interesse()]))
        cache = CacheFiltros(repo)
        self.assertIsNone(cache.filtros)
        await cache.atualizar()
        antigo = cache.preparados
        versao = cache.versao
        instante = cache.atualizado_em
        repo.carregar_filtros.return_value = [global_(palavras_bloqueio=[])]
        with self.assertRaises(ValueError):
            await cache.atualizar()
        self.assertIs(cache.preparados, antigo)
        self.assertEqual(cache.versao, versao)
        self.assertEqual(cache.atualizado_em, instante)
        repo.carregar_filtros.return_value = []
        await cache.atualizar()
        self.assertEqual(cache.preparados, ())
        self.assertEqual(cache.filtros, [])

    async def test_config_invalida_inicial_continua_desconhecida(self) -> None:
        repo = SimpleNamespace(carregar_filtros=AsyncMock(return_value=[{"preco_max": "nan"}]))
        cache = CacheFiltros(repo)
        with self.assertRaises(ValueError):
            await cache.atualizar()
        self.assertIsNone(cache.filtros)
        self.assertIsNone(cache.preparados)
