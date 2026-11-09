"""SQLite real + contratos remotos falsos; NÃO comprova atomicidade Postgres.

Todos os produtos, textos, condições e destinos são sintéticos. Os casos positivos
usam o identificar real, inclusive Amazon/ML; não há patch fabricando identidade.
"""

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cenarios_identidade import (
    AMAZON, MERCADO_LIVRE, RepositorioIdentidadeFake, ResolvedorFake, StorageFake,
    TelegramFake, aguardar, contexto_forte, linhas, mensagem_sintetica,
)
from src.cache import CacheFiltros
from src.config import Config
from src.dedup import gerar_hash
from src.estado import EstadoLocal
from src.pipeline_identidade import PipelineIdentidade
from src.repository import RepositorioSupabase
from src.repository import ResultadoOferta
from tests.test_repository import ClienteFake


class TestPipelineIdentidade(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="identidade-integracao-")
        self.diretorio = Path(self.tmp.name)
        self.config = replace(Config(), state_dir=self.diretorio, oferta_workers=2,
                              retry_base=.01, retry_max=.02, shutdown_timeout=.05,
                              resolucao_timeout=10)
        self.repo = RepositorioIdentidadeFake()
        self.storage = StorageFake()
        self.telegram = TelegramFake()
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.resolvedor = ResolvedorFake()
        self.pipeline = self.criar_pipeline()

    def criar_pipeline(self):
        return PipelineIdentidade(self.estado, self.repo, self.storage, self.telegram,
                                 self.cache, self.config, resolvedor=self.resolvedor)

    async def asyncTearDown(self):
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def reiniciar(self):
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.resolvedor = ResolvedorFake()
        self.pipeline = self.criar_pipeline()

    async def processar(self, mensagem):
        await self.estado.registrar(mensagem)
        job = await self.estado.obter_oferta(time.time(), True)
        self.assertIsNotNone(job)
        await self.pipeline._oferta(job)
        return await self.estado.evento(mensagem.canal_id, mensagem.msg_id)

    async def finalizada(self, canal, msg):
        evento = await self.estado.evento(canal, msg)
        return bool(evento and evento["finalizado_em"])

    async def enriquecimentos_finalizados(self):
        return not await linhas(self.estado, "SELECT 1 FROM enriquecimentos WHERE finalizado_em IS NULL")

    async def test_formatos_fortes_reais_amazon_e_ml_um_card_duas_aparicoes(self):
        for ml, url, sufixos in (
            (False, AMAZON, ("?smid=SELLER1&tag=canal-a-20&linkCode=ll1",
                             "?tag=canal-b-20&smid=SELLER1&linkCode=ll1")),
            (True, MERCADO_LIVRE, ("", "")),
        ):
            with self.subTest(ml=ml):
                anteriores = len(self.repo.ativos)
                for indice, sufixo in enumerate(sufixos):
                    evento = await self.processar(mensagem_sintetica(
                        10 + int(ml), -100111 - indice, url=url + sufixo,
                        contexto=contexto_forte(ml=ml)))
                    self.assertEqual(json.loads(evento["identidade"])["motivo"], "identidade_forte")
                    self.assertEqual(json.loads(evento["decisao"])["link"], url + sufixo)
                self.assertEqual(len(self.repo.ativos), anteriores + 1)
        self.assertEqual(len(self.repo.aparicoes), 4)
        self.assertEqual(len(self.repo.observacoes), 4)
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(await linhas(self.estado, "SELECT * FROM enriquecimentos"), [])

    async def test_mesmo_titulo_preco_url_opaca_nao_funde_sem_prova(self):
        for canal in (-100111, -100222):
            evento = await self.processar(mensagem_sintetica(canal=canal,
                url="https://amzn.to/AbC", contexto={}))
            self.assertIsNone(json.loads(evento["identidade"])["chave"])
        self.assertEqual(len(self.repo.ativos), 2)
        self.assertEqual(len(self.repo.aparicoes), 2)

    async def test_barreira_resolvedor_ocupado_ofertas_e_midia_avancam_depois_fundem(self):
        self.resolvedor.liberar.clear()
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem_sintetica(url="https://amzn.to/AbC", foto=True))
        await asyncio.wait_for(self.resolvedor.iniciou.wait(), 10)
        # A primeira requisição chegou à barreira somente após o efeito e vínculo.
        primeiro = await self.estado.evento(-100111, 1)
        self.assertIsNotNone(primeiro["produto_id"])
        self.assertIsNotNone(primeiro["disponibilizado_em"])
        self.assertEqual(len(self.repo.aparicoes), 1)
        await self.pipeline.receber(mensagem_sintetica(canal=-100222, url="https://meli.la/XyZ"))
        await aguardar(lambda: self.finalizada(-100111, 1), pipeline=self.pipeline)
        await aguardar(lambda: self.finalizada(-100222, 1), pipeline=self.pipeline)

        async def foto_pronta():
            return bool(self.repo.cards[1]["foto_url"])
        await aguardar(foto_pronta, pipeline=self.pipeline)
        self.assertFalse(self.resolvedor.liberar.is_set())
        self.assertEqual(len(self.repo.ativos), 2)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(self.pipeline.ativos["enriquecimento"], 1)
        self.assertIsNone(await self.estado.obter_confirmacao())
        self.resolvedor.liberar.set()
        await aguardar(self.enriquecimentos_finalizados, pipeline=self.pipeline)
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(len(self.repo.observacoes), 2)
        self.assertEqual(self.repo.aliases, {2: 1})
        self.assertEqual((await self.repo.buscar_produto(2))["id"], 1)
        self.assertEqual(len(self.storage.objetos), 1)
        self.assertEqual(self.storage.removidos, [])
        self.assertLessEqual(self.pipeline.max_ativos["oferta"], 2)
        self.assertEqual(self.pipeline.max_ativos["enriquecimento"], 1)
        self.assertEqual(self.resolvedor.max_ativos, 1)
        self.assertEqual(len(self.pipeline.tasks), 5)  # 2 ofertas + mídia + enriquecimento + ack

    async def test_cache_positivo_persistido_restart_dedup_sem_nova_resolucao(self):
        url = "https://amzn.to/CacheAbC"
        await self.processar(mensagem_sintetica(url=url))
        job = await self.estado.obter_enriquecimento(time.time())
        await self.pipeline._enriquecer(job)
        self.assertEqual(self.resolvedor.chamadas, [url])
        await self.reiniciar()
        self.assertEqual((await self.estado.cache_url(url, time.time()))["url_final"], AMAZON)
        evento = await self.processar(mensagem_sintetica(canal=-100222, url=url))
        self.assertIsNotNone(json.loads(evento["identidade"])["chave"])
        self.assertEqual(evento["estado"], "duplicata")
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(len(await linhas(self.estado, "SELECT * FROM enriquecimentos")), 1)

    async def test_cache_negativo_restart_nao_repete_rede_e_nao_funde(self):
        url = "https://amzn.to/Negativo"
        self.resolvedor.resultado = {"estado": "negativo", "url_final": None, "motivo": "timeout_sintetico"}
        await self.processar(mensagem_sintetica(url=url))
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        await self.reiniciar()
        await self.processar(mensagem_sintetica(canal=-100222, url=url))
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(len(self.repo.ativos), 2)
        self.assertEqual(self.repo.chamadas["enriquecer"], 0)

    async def test_cache_expirado_ou_versao_incompativel_nao_e_prova(self):
        for indice, versao in enumerate((1, 2)):
            url = f"https://amzn.to/Versao{indice}"
            await self.estado.guardar_cache_url(url,
                {"estado": "positivo", "url_final": AMAZON}, time.time() + 3600 if versao == 1 else 0)
            if versao == 1:
                def invalidar():
                    with self.estado._conexao():
                        self.estado._conexao().execute("UPDATE cache_urls SET versao=1 WHERE url=?", (url,))
                await self.estado._executar(invalidar)
            evento = await self.processar(mensagem_sintetica(msg_id=indice + 1, url=url))
            self.assertIsNone(json.loads(evento["identidade"])["chave"])
        self.assertEqual(len(self.repo.ativos), 2)

    async def test_resultado_positivo_sem_identidade_verificavel_preserva_originais(self):
        for canal, url in ((-100111, "https://amzn.to/Incerto"), (-100222, "https://meli.la/Incerto")):
            await self.processar(mensagem_sintetica(canal=canal, url=url, contexto={}))
            await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertTrue(await self.enriquecimentos_finalizados())
        self.assertEqual(len(self.repo.ativos), 2)
        self.assertEqual({c["link"] for c in self.repo.ativos},
                         {"https://amzn.to/Incerto", "https://meli.la/Incerto"})
        self.assertEqual(self.repo.chamadas["enriquecer"], 0)
        self.assertEqual(self.repo.aliases, {})

    async def test_timeout_resolvedor_nao_oculta_oferta_nem_cria_loop_de_rede(self):
        self.pipeline.config = replace(self.config, resolucao_timeout=.03)
        self.resolvedor.liberar.clear()
        await self.processar(mensagem_sintetica(url="https://amzn.to/Timeout"))
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(self.repo.ativos[0]["link"], "https://amzn.to/Timeout")
        self.assertIsNone(await self.estado.obter_enriquecimento(time.time()))
        resultado = (await linhas(self.estado, "SELECT * FROM enriquecimentos"))[0]
        self.assertEqual(resultado["tentativas"], 1)
        self.assertEqual(resultado["estado"], "retry")
        self.assertIsNone(resultado["resultado"])
        self.assertGreater(resultado["proxima"], time.time())
        # O ciclo é finito mesmo após cancelamentos/erros de transporte.
        await self.estado.atualizar_enriquecimento(resultado, tentativas=self.config.resolucao_tentativas, proxima=0)
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertIsNone(await self.estado.obter_enriquecimento(time.time() + 100000))
        self.assertEqual(len(self.resolvedor.chamadas), 1)
        self.assertEqual(self.repo.chamadas["enriquecer"], 0)

    async def verificar_checkpoint_rpc(self, depois_do_efeito):
        for canal, url in ((-100111, "https://amzn.to/RpcA"), (-100222, "https://meli.la/RpcB")):
            await self.processar(mensagem_sintetica(canal=canal, url=url))
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        if depois_do_efeito:
            self.repo.perder_resposta_enriquecer = True
        else:
            self.repo.falha_enriquecer = TimeoutError("rpc_fake_antes_do_efeito")
        job = await self.estado.obter_enriquecimento(time.time())
        congelada = await self.estado.evento(job["canal_id"], job["msg_id"])
        with self.assertRaises(TimeoutError):
            await self.pipeline._enriquecer(job)
        checkpoint = (await linhas(self.estado, "SELECT * FROM enriquecimentos WHERE canal_id=?",
                                   (job["canal_id"],)))[0]
        self.assertEqual(json.loads(checkpoint["resultado"])["url_final"], AMAZON)
        self.assertEqual(checkpoint["tentativas"], 1)
        self.assertEqual(len(self.resolvedor.chamadas), 2)
        await self.reiniciar()  # claim processando vira retry; resultado não é perdido
        retomada = await self.estado.obter_enriquecimento(time.time())
        self.assertEqual(retomada["estado"], "retry")
        await self.pipeline._enriquecer(retomada)
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(len(self.repo.observacoes), 2)
        self.assertTrue(await self.enriquecimentos_finalizados())
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        for campo in ("decisao", "hash", "identidade", "diagnostico"):
            self.assertEqual(evento[campo], congelada[campo])

    async def test_checkpoint_resultado_rpc_falha_antes_sem_repetir_rede(self):
        await self.verificar_checkpoint_rpc(False)

    async def test_checkpoint_resultado_rpc_resposta_perdida_sem_repetir_rede(self):
        await self.verificar_checkpoint_rpc(True)

    async def test_resposta_gravacao_perdida_retorna_evento_sem_refiltrar(self):
        self.repo.perder_resposta_salvar = True
        await self.estado.registrar(mensagem_sintetica())
        job = await self.estado.obter_oferta(time.time(), True)
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(job)
        congelada = await self.estado.evento(-100111, 1)
        await self.reiniciar()
        self.cache.filtros = [{"palavras_bloqueio": ["notebook"]}]
        job = await self.estado.obter_oferta(time.time(), True)
        with patch("src.pipeline_identidade.avaliar_mensagem", side_effect=AssertionError("refiltrou")), \
             patch("src.pipeline_identidade.identificar", side_effect=AssertionError("reidentificou")), \
             patch("src.pipeline_identidade.gerar_hash", side_effect=AssertionError("recalculou")):
            await self.pipeline._oferta(job)
        evento = await self.estado.evento(-100111, 1)
        self.assertEqual(evento["estado"], "aprovada")
        self.assertEqual(evento["resultado"], "retomado")
        for campo in ("decisao", "hash", "identidade", "diagnostico"):
            self.assertEqual(evento[campo], congelada[campo])
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 1)
        self.assertEqual(len(self.repo.observacoes), 1)

    async def test_decisao_legada_antiga_preserva_hash_sem_refiltro_ou_identidade(self):
        cliente = ClienteFake()
        self.pipeline.repositorio = RepositorioSupabase(cliente)
        await self.estado.configurar_canal(-100111, "sintetico", 123, 0,
                                           aliases_extras=["@antigo"])
        await self.estado.registrar(replace(mensagem_sintetica(), data_origem="2020-01-01T00:00:00+00:00"))
        job = await self.estado.obter_oferta(time.time(), True)
        produto = {"titulo": "Congelado legado", "preco": 0, "link": "https://legado.invalid/A"}
        hash_congelado = "a" * 32  # Formato MD5 válido, diferente do hash do produto.
        await self.estado.decidir(job, produto, hash_congelado, {"snapshot": 1})
        await self.estado.adiar_oferta(job, "retry", 0, "resposta_ambigua")
        self.cache.filtros = None
        with patch("src.pipeline.avaliar_mensagem", side_effect=AssertionError("refiltro legado")), \
             patch("src.pipeline_identidade.identificar", side_effect=AssertionError("identidade legado")), \
             patch("src.pipeline.gerar_hash", side_effect=AssertionError("hash legado")):
            await self.pipeline._oferta(await self.estado.obter_oferta(time.time(), False))
        evento = await self.estado.evento(-100111, 1)
        self.assertEqual(evento["hash"], hash_congelado)
        self.assertIsNone(evento["identidade"])
        self.assertEqual(json.loads(evento["decisao"]), produto)
        self.assertEqual(cliente.tabelas["produtos"][0]["dedup_hash"], hash_congelado)
        self.assertEqual(len(cliente.tabelas["produto_aparicoes"]), 1)
        self.assertEqual(self.repo.chamadas["salvar_identificada"], 0)

    async def test_legado_sem_hash_fallback_so_produto_congelado(self):
        cliente = ClienteFake()
        self.pipeline.repositorio = RepositorioSupabase(cliente)
        await self.estado.registrar(mensagem_sintetica())
        job = await self.estado.obter_oferta(time.time(), True)
        produto = {"titulo": "Somente decisão congelada", "preco": 42, "link": "https://legado.invalid/B"}
        await self.estado.decidir(job, produto, None)
        self.cache.filtros = None
        job = await self.estado.evento(-100111, 1)
        with patch("src.pipeline.avaliar_mensagem", side_effect=AssertionError("refiltro")), \
             patch("src.pipeline_identidade.identificar", side_effect=AssertionError("reidentificou")):
            await self.pipeline._oferta(job)
        self.assertEqual(cliente.tabelas["produtos"][0]["dedup_hash"], gerar_hash(produto))

    async def test_preflight_legado_fixa_pin_antes_de_liberar_limpeza_sem_refiltro(self):
        await self.estado.registrar(mensagem_sintetica())
        job = await self.estado.obter_oferta(time.time(), True)
        produto = {"titulo": "Congelado legado", "preco": 0, "link": "https://legado.invalid/A"}
        congelado = "b" * 32
        await self.estado.decidir(job, produto, congelado)
        chamadas = []

        async def salvar_legada(evento, decisao, hash_legado, aliases):
            chamadas.append((evento["msg_id"], decisao, hash_legado))
            return ResultadoOferta(21, "retomado", None)

        async def prontos():
            self.assertEqual(len(chamadas), 1)
            self.assertEqual((await self.estado.evento(-100111, 1))["referencia_remota"], 1)
        self.repo.salvar_legada = salvar_legada
        self.repo.legados_prontos = prontos
        self.cache.filtros = None
        with patch("src.pipeline_identidade.avaliar_mensagem", side_effect=AssertionError("refiltro")), \
             patch("src.pipeline_identidade.identificar", side_effect=AssertionError("identidade nova")), \
             patch("src.pipeline_identidade.gerar_hash", side_effect=AssertionError("recalculou")):
            await self.pipeline.preparar_legados()
            await self.pipeline._oferta(await self.estado.evento(-100111, 1))
        atual = await self.estado.evento(-100111, 1)
        self.assertEqual(atual["hash"], congelado)
        self.assertEqual(json.loads(atual["decisao"]), produto)
        self.assertIsNone(atual["identidade"])
        self.assertEqual(atual["produto_id"], 21)
        self.assertEqual((await self.estado.limpar(time.time()+100))["eventos"], 0)
        ack = await self.estado.obter_confirmacao()
        self.assertEqual(ack, {"canal_id": -100111, "msg_id": 1})
        await self.estado.confirmar_remoto(ack)
        self.assertEqual((await self.estado.limpar(time.time()+100))["eventos"], 1)

    async def test_preflight_incompativel_nao_libera_gate_remoto_nem_faz_fallback(self):
        from unittest.mock import AsyncMock
        await self.estado.registrar(mensagem_sintetica())
        job = await self.estado.obter_oferta(time.time(), True)
        await self.estado.decidir(job, {"titulo": "Legado", "preco": 1}, "b"*32)
        self.repo.salvar_legada = AsyncMock(side_effect=RuntimeError("schema_ausente"))
        self.repo.legados_prontos = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "schema_ausente"):
            await self.pipeline.preparar_legados()
        self.repo.legados_prontos.assert_not_awaited()
        self.assertEqual((await self.estado.evento(-100111, 1))["referencia_remota"], 0)
        self.assertEqual(len(self.repo.ativos), 0)

    async def test_schema_ausente_worker_preserva_decisao_e_retry_sem_fallback(self):
        self.repo.schema_disponivel = False
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem_sintetica())

        async def em_retry():
            evento = await self.estado.evento(-100111, 1)
            return evento["estado"] == "retry" and evento["decisao"] is not None
        await aguardar(em_retry, pipeline=self.pipeline)
        await self.pipeline.encerrar()
        antes = await self.estado.evento(-100111, 1)
        self.assertIsNone(antes["finalizado_em"])
        self.assertIsNone(antes["produto_id"])
        self.assertEqual(self.repo.ativos, [])
        self.assertEqual((await self.estado.limpar(time.time() + 100))["eventos"], 0)
        self.repo.schema_disponivel = True
        await self.reiniciar()
        self.cache.filtros = None
        with patch("src.pipeline_identidade.avaliar_mensagem", side_effect=AssertionError("refiltro")):
            await self.pipeline._oferta(await self.estado.obter_oferta(time.time() + 100, False))
        depois = await self.estado.evento(-100111, 1)
        self.assertEqual(depois["decisao"], antes["decisao"])
        self.assertEqual(depois["identidade"], antes["identidade"])
        self.assertEqual(len(self.repo.ativos), 1)

    async def test_serializacao_e_deadlock_retornam_a_fila_sem_redecidir(self):
        class FalhaSQL(Exception):
            def __init__(self, code):
                super().__init__("falha SQL sintética")
                self.code = code
        salvar = self.repo.salvar_identificada
        codigos = ["40001", "40P01"]
        chamadas = []

        async def transitoria(job, produto, identidade, janela):
            chamadas.append((job["hash"], json.dumps(identidade, sort_keys=True)))
            if codigos:
                raise FalhaSQL(codigos.pop(0))
            return await salvar(job, produto, identidade, janela)
        self.repo.salvar_identificada = transitoria
        from src.pipeline_identidade import avaliar_mensagem
        with patch("src.pipeline_identidade.avaliar_mensagem", wraps=avaliar_mensagem) as avaliar:
            self.pipeline.iniciar()
            await self.pipeline.receber(mensagem_sintetica())
            await aguardar(lambda: self.finalizada(-100111, 1), pipeline=self.pipeline)
            self.assertEqual(avaliar.call_count, 1)
        self.assertEqual(len(chamadas), 3)
        self.assertEqual(len(set(chamadas)), 1)
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 1)

    async def test_retencao_conserva_fonte_ate_midia_enriquecimento_e_ack(self):
        evento = await self.processar(mensagem_sintetica(url="https://amzn.to/Retencao", foto=True))
        antes = time.time() + 100
        self.assertEqual(await self.estado.limpar(antes), {"eventos": 0, "midias": 0})
        self.assertIsNone(await self.estado.obter_confirmacao())
        job = await self.estado.obter_enriquecimento(time.time())
        await self.pipeline._enriquecer(job)
        self.assertEqual((await self.estado.limpar(antes))["eventos"], 0)
        self.assertIsNone(await self.estado.obter_confirmacao())
        await self.pipeline._midia(await self.estado.obter_midia(time.time()))
        # Fonte e resultado ainda protegidos até confirmação remota durável.
        self.assertEqual((await self.estado.limpar(antes))["eventos"], 0)
        await self.estado.limpar_enriquecimentos(antes, time.time(), 100)
        self.assertEqual(len(await linhas(self.estado, "SELECT * FROM enriquecimentos")), 1)
        confirmacao = await self.estado.obter_confirmacao()
        self.assertEqual(confirmacao, {"canal_id": -100111, "msg_id": 1})
        await self.repo.confirmar_evento(confirmacao)
        await self.estado.confirmar_remoto(confirmacao)
        self.assertEqual((await self.estado.limpar(antes))["eventos"], 1)
        await self.estado.limpar_enriquecimentos(antes, time.time(), 100)
        self.assertEqual(await linhas(self.estado, "SELECT * FROM enriquecimentos"), [])
        self.assertIsNone(await self.estado.evento(-100111, 1))
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertIsNotNone(self.repo.cards[evento["produto_id"]]["foto_url"])

    async def test_shutdown_devolve_claim_enriquecimento_e_reinicio_conclui(self):
        self.resolvedor.liberar.clear()
        self.pipeline.iniciar()
        await self.pipeline.receber(mensagem_sintetica(url="https://amzn.to/Shutdown"))
        await asyncio.wait_for(self.resolvedor.iniciou.wait(), 10)
        await self.pipeline.encerrar()
        fila = (await linhas(self.estado, "SELECT * FROM enriquecimentos"))[0]
        self.assertEqual(fila["estado"], "retry")
        self.assertEqual(fila["tentativas"], 1)
        self.assertTrue(self.resolvedor.fechado)
        await self.reiniciar()
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertTrue(await self.enriquecimentos_finalizados())
        self.assertEqual(len(self.repo.ativos), 1)


class TestMigracaoIdentidadeV6(unittest.IsolatedAsyncioTestCase):
    async def test_v5_sintetica_preserva_decisao_hash_claim_midia_fronteiras(self):
        with tempfile.TemporaryDirectory(prefix="identidade-v5-") as temporario:
            diretorio = Path(temporario)
            # Schema v5 independente do migrador novo: não cria v6 para depois
            # só trocar user_version, o que esconderia colunas ausentes.
            with sqlite3.connect(diretorio / "inbox.sqlite3") as db:
                db.executescript("""
                    CREATE TABLE canais(canal_id INTEGER PRIMARY KEY,username TEXT NOT NULL,
                        access_hash TEXT,aliases TEXT NOT NULL DEFAULT '[]',cursor INTEGER NOT NULL DEFAULT 0,
                        bootstrap REAL NOT NULL,limite INTEGER,proxima REAL NOT NULL DEFAULT 0,
                        tentativas INTEGER NOT NULL DEFAULT 0,erro TEXT,ativo INTEGER NOT NULL DEFAULT 1,
                        geracao INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE eventos(canal_id INTEGER NOT NULL,msg_id INTEGER NOT NULL,
                        username TEXT NOT NULL,remoto_canal TEXT NOT NULL,texto TEXT NOT NULL,
                        data_origem TEXT NOT NULL,recebido_em REAL NOT NULL,origem TEXT NOT NULL,
                        tem_foto INTEGER NOT NULL,estado TEXT NOT NULL DEFAULT 'pendente',
                        tentativas INTEGER NOT NULL DEFAULT 0,proxima REAL NOT NULL DEFAULT 0,erro TEXT,
                        decisao TEXT,hash TEXT,produto_id INTEGER,resultado TEXT,finalizado_em REAL,
                        disponibilizado_em REAL,contexto TEXT NOT NULL DEFAULT '{}',
                        diagnostico TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(canal_id,msg_id));
                    CREATE TABLE midias(produto_id INTEGER PRIMARY KEY,canal_id INTEGER NOT NULL,
                        msg_id INTEGER NOT NULL,chave TEXT NOT NULL UNIQUE,estado TEXT NOT NULL DEFAULT 'pendente',
                        tentativas INTEGER NOT NULL DEFAULT 0,proxima REAL NOT NULL DEFAULT 0,erro TEXT,
                        url TEXT,enviado INTEGER NOT NULL DEFAULT 0,compensar INTEGER NOT NULL DEFAULT 0,
                        finalizado_em REAL,falha_apos_limpeza TEXT);
                    CREATE TABLE donos_hash(hash TEXT PRIMARY KEY,canal_id INTEGER NOT NULL,msg_id INTEGER NOT NULL);
                    CREATE TABLE resolucoes(username TEXT PRIMARY KEY,proxima REAL NOT NULL DEFAULT 0,
                        tentativas INTEGER NOT NULL DEFAULT 0,erro TEXT);
                    PRAGMA user_version=5;
                """)
                decisao = '{"titulo": "Legado sintético", "preco": 0, "link": "https://legado.invalid/A"}'
                db.execute("INSERT INTO canais(canal_id,username,aliases,cursor,bootstrap,limite,geracao) VALUES(?,?,?,?,?,?,?)",
                           (-100111, "novo", '["antigo","@novo"]', 23, 123, 42, 3))
                db.execute("""INSERT INTO eventos(canal_id,msg_id,username,remoto_canal,texto,data_origem,
                    recebido_em,origem,tem_foto,estado,tentativas,decisao,hash,produto_id,contexto,diagnostico)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (-100111, 7, "antigo", "@antigo", "Texto antigo", "2020-01-01T00:00:00+00:00",
                            123, "historico", 1, "processando", 4, decisao, "HASH-congelado", 81,
                            '{"links": []}', '{"snapshot": 9}'))
                db.execute("INSERT INTO donos_hash VALUES('HASH-congelado',-100111,7)")
                db.execute("""INSERT INTO midias(produto_id,canal_id,msg_id,chave,estado,tentativas,url,enviado,compensar)
                    VALUES(81,-100111,7,'81_-100111_7.jpg','processando',2,'https://storage.invalid/antiga',1,1)""")
                db.execute("INSERT INTO resolucoes VALUES('canal_pendente',456,2,'FloodWait')")
            estado = EstadoLocal(diretorio)
            try:
                await estado.abrir()
                evento = await estado.evento(-100111, 7)
                self.assertEqual((await linhas(estado, "PRAGMA user_version"))[0]["user_version"], 6)
                self.assertEqual(evento["decisao"], decisao)
                self.assertEqual(evento["hash"], "HASH-congelado")
                self.assertEqual(evento["produto_id"], 81)
                self.assertEqual(evento["estado"], "retry")
                self.assertEqual(evento["tentativas"], 4)
                self.assertEqual(evento["contexto"], '{"links": []}')
                self.assertEqual(evento["diagnostico"], '{"snapshot": 9}')
                self.assertIsNone(evento["identidade"])
                self.assertEqual(evento["remoto_confirmado"], 0)
                canal = await estado.canal(-100111)
                self.assertEqual((canal["cursor"], canal["limite"], canal["geracao"]), (23, 42, 3))
                self.assertEqual(json.loads(canal["aliases"]), ["antigo", "@novo"])
                midia = await estado.midia(81)
                self.assertEqual((midia["estado"], midia["tentativas"], midia["enviado"], midia["compensar"]),
                                 ("retry", 2, 1, 1))
                self.assertEqual(len(await linhas(estado, "SELECT * FROM donos_hash")), 1)
                self.assertEqual((await estado.resolucao("canal_pendente"))["tentativas"], 2)
                self.assertEqual(await linhas(estado, "SELECT * FROM cache_urls"), [])
                self.assertEqual(await estado.limpar(time.time() + 100), {"eventos": 0, "midias": 0})
            finally:
                await estado.fechar()
            # Segunda abertura não recongela nem recalcula dados legados.
            estado = EstadoLocal(diretorio)
            try:
                await estado.abrir()
                self.assertEqual((await estado.evento(-100111, 7))["decisao"], decisao)
                self.assertEqual((await estado.midia(81))["compensar"], 1)
            finally:
                await estado.fechar()


class TestSimulacaoIdentidade(unittest.IsolatedAsyncioTestCase):
    async def test_cenarios_comparaveis_medem_antes_e_depois_da_barreira(self):
        from simulacao_identidade import Parametros, executar
        resultado = await executar(Parametros(seed=42, pares=1, db_ms=0, resolucao_ms=5, prazo=20))
        cenarios = {r["cenario"]: r for r in resultado["resultados"]}
        self.assertEqual(set(cenarios), {"fortes", "frio", "quente", "lento"})
        self.assertEqual(len({cenarios[c]["dataset_sha256"] for c in ("frio", "quente", "lento")}), 1)
        for nome, cenario in cenarios.items():
            with self.subTest(cenario=nome):
                self.assertEqual(cenario["apos_convergencia"]["cards_ativos_fake"], 1)
                self.assertEqual(cenario["apos_convergencia"]["aparicoes_fake"], 2)
                self.assertFalse(any(cenario["apos_convergencia"]["pendencias"].values()))
                for origem in ("live", "historico"):
                    self.assertEqual(cenario["latencia_oferta_ms"][origem]["quantidade"], 1)
                    self.assertIsNotNone(cenario["latencia_oferta_ms"][origem]["p95"])
                self.assertLessEqual(cenario["workers"]["max_ativos"]["enriquecimento"], 1)
        for nome in ("frio", "lento"):
            self.assertEqual(cenarios[nome]["antes_liberar_resolucao"]["cards_ativos_fake"], 2)
            self.assertEqual(cenarios[nome]["barreira"]["ofertas_salvas_antes_de_liberar"], 2)
            self.assertTrue(cenarios[nome]["barreira"]["resposta_ainda_bloqueada"])
            self.assertEqual(cenarios[nome]["resolucoes_fake"], 2)
        self.assertEqual(cenarios["quente"]["resolucoes_fake"], 0)
        self.assertEqual(cenarios["quente"]["cache_hits_caminho_oferta"], 2)
        self.assertEqual(cenarios["fortes"]["resolucoes_fake"], 0)

    def test_parametros_invalidos_nao_geram_carga_ou_espera_ilimitada(self):
        from simulacao_identidade import Parametros
        for argumento in ({"pares": 0}, {"pares": True}, {"db_ms": -1},
                          {"prazo": 0}, {"resolucao_ms": float("inf")},
                          {"enriquecimento_workers": 9}, {"cenario": "desconhecido"}):
            with self.subTest(argumento=argumento), self.assertRaises(ValueError):
                Parametros(**argumento)


if __name__ == "__main__":
    unittest.main()
