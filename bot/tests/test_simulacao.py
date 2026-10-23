import unittest

from simulacao import Parametros, executar


class TestSimulacao(unittest.IsolatedAsyncioTestCase):
    async def test_smoke_limites_seed_e_backlog(self) -> None:
        parametros = Parametros(seed=42, live=3, historico=12, db_ms=2,
                                midia_ms=10000, oferta_workers=2, midia_workers=1)
        resultado = await executar(parametros)
        self.assertEqual(resultado["contagens"]["recebidas"], 15)
        self.assertEqual(resultado["contagens"]["produtos"], 15)
        self.assertEqual(resultado["contagens"]["ofertas"], {"aprovada": 15})
        for origem, quantidade in (("live", 3), ("historico", 12)):
            latencias = resultado["latencia_recebimento_commit_ms"][origem]
            self.assertEqual(latencias["quantidade"], quantidade)
            self.assertGreater(latencias["p50"], 0)
            self.assertEqual(resultado["filas"][origem]["final"], 0)
        self.assertGreater(resultado["filas"]["midia"]["final"], 0)
        self.assertLessEqual(resultado["limites_memoria"]["pagina_max_observada"], 100)
        self.assertEqual(resultado["limites_memoria"]["tasks_por_mensagem"], 0)
        for classe, limite in (("oferta", 2), ("midia", 1)):
            self.assertLessEqual(resultado["workers"]["max_ativos"][classe], limite)
        # A carga minúscula pode acabar antes de existir backlog das duas classes.
        # Justiça com ambas elegíveis é testada diretamente na fila/pipeline.
        self.assertEqual(set(resultado["progresso_antes_fim_outra_classe"]), {"live", "historico"})
        repetido = await executar(parametros)
        self.assertEqual(resultado["dataset_sha256"], repetido["dataset_sha256"])
        outro = await executar(Parametros(seed=43, live=3, historico=12, db_ms=0,
                                          midia_ms=10000, oferta_workers=2))
        self.assertNotEqual(resultado["dataset_sha256"], outro["dataset_sha256"])

    async def test_midia_falha_e_paginacao(self) -> None:
        resultado = await executar(Parametros(live=0, historico=101, db_ms=0,
                                              midia_ms=0, midia_falha=True))
        self.assertEqual(resultado["limites_memoria"]["pagina_max_observada"], 100)
        self.assertEqual(resultado["contagens"]["ofertas"], {"aprovada": 101})
        self.assertGreater(resultado["contagens"]["midia_falhas"], 0)
        self.assertGreater(resultado["filas"]["midia"]["final"], 0)
        self.assertEqual(resultado["latencia_recebimento_commit_ms"]["live"]["quantidade"], 0)

    def test_parametros_invalidos(self) -> None:
        for campos in ({"live": -1}, {"live": 0, "historico": 0},
                       {"oferta_workers": 0}, {"db_ms": float("nan")}, {"midia_ms": -1}):
            with self.subTest(campos=campos), self.assertRaises(ValueError):
                Parametros(**campos)
