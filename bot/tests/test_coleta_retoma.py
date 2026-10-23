"""Retomada de coleta, ativação concorrente e retries anteriores ao ID Telegram."""

import asyncio
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.config import Config
from src.estado import EstadoLocal
from src.modelos import Mensagem
from src.recuperacao import Recuperacao
from src.telegram import Telegram
from tests.test_regressoes_telethon import CANAL_ID, DATA, TEM_TELETHON, cliente_historico


class TestColetaRetoma(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.diretorio = Path(self.tmp.name)
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.addAsyncCleanup(self.fechar_estado)
        self.repo = SimpleNamespace(listar_canais=AsyncMock(return_value=["canal"]))
        self.tg = SimpleNamespace(
            resolver=AsyncMock(return_value={"canal_id": CANAL_ID, "username": "canal", "access_hash": 1}),
            mais_nova=AsyncMock(return_value=10), pagina=AsyncMock(return_value=([], True)))
        self.rec = Recuperacao(self.estado, self.repo, self.tg, Config(), asyncio.Event())

    async def fechar_estado(self) -> None:
        await self.estado.fechar()

    async def reiniciar(self) -> None:
        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.rec = Recuperacao(self.estado, self.repo, self.tg, Config(), asyncio.Event())

    def mensagem(self, msg_id: int) -> Mensagem:
        return Mensagem(CANAL_ID, msg_id, "canal", "teste", DATA.isoformat(), origem="historico")

    async def preparar_historico(self, limite: int) -> None:
        await self.estado.configurar_canal(CANAL_ID, "canal", 1, DATA.timestamp() - 86400)
        await self.rec.atualizar_canais()
        await self.estado.iniciar_varredura(CANAL_ID, limite)

    async def test_desativacao_antes_do_commit_descarta_pagina_e_preserva_aceitos(self) -> None:
        await self.rec.atualizar_canais()
        await self.estado.registrar(self.mensagem(1))
        pronta, liberar = asyncio.Event(), asyncio.Event()
        registrar = self.estado.registrar_pagina

        async def commit(*args, **kwargs):
            pronta.set()
            await liberar.wait()
            return await registrar(*args, **kwargs)

        self.tg.pagina.return_value = ([self.mensagem(2)], True)
        with patch.object(self.estado, "registrar_pagina", side_effect=commit):
            rodada = asyncio.create_task(self.rec.rodada())
            try:
                await asyncio.wait_for(pronta.wait(), 5)
                self.repo.listar_canais.return_value = []
                await asyncio.wait_for(self.rec.atualizar_canais(), 5)
                # Trabalho aceito continua disponível mesmo durante a página bloqueada.
                job = await self.estado.obter_oferta(time.time(), True)
                self.assertEqual(job["msg_id"], 1)
                liberar.set()
                self.assertEqual(await asyncio.wait_for(rodada, 5), 0)
            finally:
                liberar.set()
                await asyncio.gather(rodada, return_exceptions=True)
        self.assertIsNone(await self.estado.evento(CANAL_ID, 2))
        self.assertEqual((await self.estado.canal(CANAL_ID))["cursor"], 0)

    async def test_pagina_em_voo_nao_reaparece_apos_desativar_e_reativar(self) -> None:
        await self.rec.atualizar_canais()
        geracao = (await self.estado.canal(CANAL_ID))["geracao"]
        iniciou, liberar = asyncio.Event(), asyncio.Event()

        async def pagina(canal, quantidade):
            iniciou.set()
            await liberar.wait()
            return [self.mensagem(2)], True

        self.tg.pagina.side_effect = pagina
        rodada = asyncio.create_task(self.rec.rodada())
        try:
            await asyncio.wait_for(iniciou.wait(), 5)
            self.repo.listar_canais.return_value = []
            await asyncio.wait_for(self.rec.atualizar_canais(), 5)
            self.repo.listar_canais.return_value = ["canal"]
            await asyncio.wait_for(self.rec.atualizar_canais(), 5)
            canal = await self.estado.canal(CANAL_ID)
            self.assertTrue(canal["ativo"])
            self.assertGreater(canal["geracao"], geracao)
            liberar.set()
            self.assertEqual(await asyncio.wait_for(rodada, 5), 0)
        finally:
            liberar.set()
            await asyncio.gather(rodada, return_exceptions=True)
        self.assertIsNone(await self.estado.evento(CANAL_ID, 2))
        self.tg.pagina.side_effect = None
        self.tg.pagina.return_value = ([self.mensagem(2)], True)
        self.assertEqual(await self.rec.rodada(), 1)
        self.assertIsNotNone(await self.estado.evento(CANAL_ID, 2))

    async def test_desativacao_depois_do_commit_preserva_pagina_e_marcador(self) -> None:
        await self.rec.atualizar_canais()
        self.tg.pagina.return_value = ([self.mensagem(2)], True)
        self.assertEqual(await self.rec.rodada(), 1)
        self.repo.listar_canais.return_value = []
        await self.rec.atualizar_canais()
        self.assertEqual(await self.rec.rodada(), 0)
        self.assertIsNotNone(await self.estado.evento(CANAL_ID, 2))
        canal = await self.estado.canal(CANAL_ID)
        self.assertEqual(canal["cursor"], 10)
        self.assertFalse(canal["ativo"])

    async def test_desativacao_durante_mais_nova_impede_pedir_pagina(self) -> None:
        await self.rec.atualizar_canais()
        iniciou, liberar = asyncio.Event(), asyncio.Event()

        async def mais_nova(canal_id):
            iniciou.set()
            await liberar.wait()
            return 10

        self.tg.mais_nova.side_effect = mais_nova
        rodada = asyncio.create_task(self.rec.rodada())
        try:
            await asyncio.wait_for(iniciou.wait(), 5)
            self.repo.listar_canais.return_value = []
            await self.rec.atualizar_canais()
            liberar.set()
            await asyncio.wait_for(rodada, 5)
        finally:
            liberar.set()
            await asyncio.gather(rodada, return_exceptions=True)
        self.tg.pagina.assert_not_awaited()
        self.assertIsNone((await self.estado.canal(CANAL_ID))["limite"])

    async def test_configurar_sem_ativar_nao_abre_janela_antes_da_lista_final(self) -> None:
        await self.estado.configurar_canal(CANAL_ID, "canal", 1, 0, ativar=False)
        self.assertFalse((await self.estado.canal(CANAL_ID))["ativo"])
        await self.estado.ativar_canais([CANAL_ID])
        await self.estado.ativar_canais([])
        anterior = await self.estado.canal(CANAL_ID)
        await self.estado.configurar_canal(CANAL_ID, "alias", 2, 100, ativar=False)
        atual = await self.estado.canal(CANAL_ID)
        self.assertEqual((atual["ativo"], atual["geracao"]), (0, anterior["geracao"]))
        self.assertEqual(atual["bootstrap"], 0)

    async def _comprovar_cooldown_de_geracao_anterior(self, reativar: bool) -> None:
        class FloodWait(Exception):
            seconds = 120

        await self.rec.atualizar_canais()
        iniciou, liberar = asyncio.Event(), asyncio.Event()

        async def pagina(canal, quantidade):
            iniciou.set()
            await liberar.wait()
            raise FloodWait()

        self.tg.pagina.side_effect = pagina
        rodada = asyncio.create_task(self.rec.rodada())
        try:
            await asyncio.wait_for(iniciou.wait(), 5)
            self.repo.listar_canais.return_value = []
            await self.rec.atualizar_canais()
            if reativar:
                self.repo.listar_canais.return_value = ["canal"]
                await self.rec.atualizar_canais()
            antes = await self.estado.canal(CANAL_ID)
            momento = time.time()
            liberar.set()
            await asyncio.wait_for(rodada, 5)
            depois = await self.estado.canal(CANAL_ID)
            self.assertGreaterEqual(depois["proxima"], momento + 120)
            self.assertEqual((depois["erro"], depois["tentativas"]), ("FloodWait", 1))
            for campo in ("cursor", "limite", "ativo", "geracao"):
                self.assertEqual(depois[campo], antes[campo], "Cooldown não altera cobertura ou ativação")
            await self.reiniciar()
            self.repo.listar_canais.return_value = ["canal"]
            await self.rec.atualizar_canais()
            await self.estado.acordar_canais()
            await self.rec.rodada()
            self.assertEqual(self.tg.pagina.await_count, 1,
                             "Reativar/reiniciar não pode antecipar o FloodWait recebido pelo RPC antigo")
            self.assertEqual((await self.estado.canal(CANAL_ID))["proxima"], depois["proxima"])
        finally:
            liberar.set()
            await asyncio.gather(rodada, return_exceptions=True)

    async def test_floodwait_apos_reativar_preserva_cooldown_da_geracao_anterior(self) -> None:
        await self._comprovar_cooldown_de_geracao_anterior(reativar=True)

    async def test_floodwait_apos_desativar_persiste_ate_reativacao_e_reinicio(self) -> None:
        await self._comprovar_cooldown_de_geracao_anterior(reativar=False)

    async def test_retry_normalizado_persiste_remocao_restart_e_expira_sem_bloquear_outro(self) -> None:
        class FloodWait(Exception):
            seconds = 120

        async def resolver(nome):
            if nome == "canal":
                raise FloodWait("URL/session-string-secreta")
            return {"canal_id": CANAL_ID + 1, "username": nome, "access_hash": 1}

        self.tg.resolver.side_effect = resolver
        self.repo.listar_canais.return_value = ["@CaNaL", "outro"]
        inicio = time.time()
        await self.rec.atualizar_canais()
        retry = await self.estado.resolucao("@CANAL")
        self.assertGreaterEqual(retry["proxima"], inicio + 120)
        self.assertEqual((retry["tentativas"], retry["erro"]), (1, "FloodWait"))
        self.assertEqual(await self.estado.canais(), [await self.estado.canal(CANAL_ID + 1)])
        await self.rec.rodada()
        self.tg.pagina.assert_awaited_once()
        self.repo.listar_canais.return_value = []
        await self.rec.atualizar_canais()
        await self.reiniciar()
        self.repo.listar_canais.return_value = ["canal"]
        await self.rec.atualizar_canais()
        await self.estado.acordar_canais()
        await self.rec.atualizar_canais()
        self.assertEqual(self.tg.resolver.await_count, 2)  # canal e outro, antes do restart
        self.assertEqual(await self.estado.resolucao("canal"), retry)
        self.tg.resolver.side_effect = None
        with patch("src.recuperacao.time.time", return_value=retry["proxima"] + 1):
            await self.rec.atualizar_canais()
        self.assertEqual(self.tg.resolver.await_count, 3)
        self.assertIsNone(await self.estado.resolucao("canal"))
        self.assertIn(CANAL_ID, self.rec.ativos)

    async def test_aliases_do_mesmo_id_nao_perdem_protecao_de_vinculo(self) -> None:
        self.repo.listar_canais.return_value = ["canal", "alias"]
        await self.rec.atualizar_canais()
        await self.reiniciar()

        async def resolver(nome):
            return {"canal_id": CANAL_ID + (1 if nome == "alias" else 0),
                    "username": nome, "access_hash": 1}

        self.tg.resolver.side_effect = resolver
        await self.rec.atualizar_canais()
        self.assertEqual(set(self.rec.ativos), {CANAL_ID})
        self.assertIsNone(await self.estado.canal(CANAL_ID + 1))
        self.assertEqual((await self.estado.resolucao("alias"))["erro"], "ValueError")

    async def test_nova_falha_apos_expiracao_incrementa_tentativa_duravel(self) -> None:
        class FloodWait(Exception):
            seconds = 120

        self.tg.resolver.side_effect = FloodWait("segredo-nao-persistido")
        await self.rec.atualizar_canais()
        retry = await self.estado.resolucao("canal")
        with patch("src.recuperacao.time.time", return_value=retry["proxima"] + 1):
            await self.rec.atualizar_canais()
        segunda = await self.estado.resolucao("canal")
        self.assertEqual(segunda["tentativas"], 2)
        self.assertGreaterEqual(segunda["proxima"], retry["proxima"] + 121)
        self.assertEqual(segunda["erro"], "FloodWait")
        await self.reiniciar()
        await self.rec.atualizar_canais()
        self.assertEqual(self.tg.resolver.await_count, 2)
        self.assertEqual(await self.estado.resolucao("canal"), segunda)

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; contrato raw necessário")
    async def test_adapter_nao_reabre_rpc_apos_desativacao_em_pagina_curta(self) -> None:
        await self.preparar_historico(1137)
        iniciou, liberar = asyncio.Event(), asyncio.Event()
        base = type(cliente_historico())

        class ClientePaginaCurta(base):
            async def __call__(self, request, *args, **kwargs):
                resposta = await super().__call__(request, *args, **kwargs)
                if len(self.requisicoes) == 1:
                    resposta.messages = resposta.messages[-50:]
                    iniciou.set()
                    await liberar.wait()
                return resposta

        client = ClientePaginaCurta()
        for msg in client.historico:
            msg.id += 1000
        tg = Telegram(client, self.estado)
        rec = Recuperacao(self.estado, self.repo, tg, Config(), asyncio.Event())
        tarefa = asyncio.create_task(rec.rodada())
        try:
            await asyncio.wait_for(iniciou.wait(), 5)
            self.repo.listar_canais.return_value = []
            await self.rec.atualizar_canais()
            liberar.set()
            self.assertEqual(await asyncio.wait_for(tarefa, 5), 0)
            self.assertEqual(client.requisicoes, [(0, -100, 100)])
            self.assertEqual((await self.estado.canal(CANAL_ID))["cursor"], 0)
            self.assertEqual((await self.estado.resumo())["ofertas"], {})
        finally:
            liberar.set()
            await asyncio.gather(tarefa, return_exceptions=True)

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; contrato raw necessário")
    async def test_uma_rpc_por_rodada_confirma_prefixo_antes_de_floodwait(self) -> None:
        from telethon.errors import FloodWaitError

        await self.preparar_historico(137)
        base = type(cliente_historico())

        class ClienteLimitado(base):
            def __init__(self):
                super().__init__()
                self.na_janela = 0
                self.pedidos = []
                self.confirmados = []

            async def __call__(self, request, *args, **kwargs):
                self.pedidos.append((request.offset_id, request.add_offset, request.limit))
                self.na_janela += 1
                if self.na_janela > 10:
                    raise FloodWaitError(request=request, capture=120)
                resposta = await super().__call__(request, *args, **kwargs)
                resposta.messages = resposta.messages[-1:]
                self.confirmados.extend(m.id for m in resposta.messages)
                return resposta

        client = ClienteLimitado()
        cfg = replace(Config(), recuperacao_pausa=0.5)
        rec = Recuperacao(self.estado, self.repo, Telegram(client, self.estado), cfg, asyncio.Event())
        agora = time.time()
        esperas = []
        with patch("src.recuperacao.time.time", side_effect=lambda: agora):
            for n in range(1, 11):
                pedidos = len(client.pedidos)
                self.assertEqual(await rec.rodada(), 1)
                self.assertEqual(len(client.pedidos), pedidos + 1)
                canal = await self.estado.canal(CANAL_ID)
                self.assertEqual(canal["cursor"], n)
                self.assertIsNotNone(await self.estado.evento(CANAL_ID, n))
                self.assertEqual(canal["proxima"], agora + cfg.recuperacao_pausa)
                # O pacing persistido impede uma segunda chamada na mesma janela.
                self.assertEqual(await rec.rodada(), 0)
                self.assertEqual(len(client.pedidos), pedidos + 1)
                agora = canal["proxima"]
            self.assertEqual(await rec.rodada(), 0)
            self.assertEqual(len(client.pedidos), 11)
            canal = await self.estado.canal(CANAL_ID)
            self.assertEqual(canal["cursor"], 10)
            self.assertGreaterEqual(canal["proxima"], agora + 120)
            esperas.append(canal["proxima"] - agora)
            await self.reiniciar()
            rec = Recuperacao(self.estado, self.repo, Telegram(client, self.estado), cfg, asyncio.Event())
            await self.estado.acordar_canais()
            await rec.rodada()
            self.assertEqual(len(client.pedidos), 11)
            client.na_janela = 0
            agora = canal["proxima"]
            while (await self.estado.canal(CANAL_ID))["cursor"] < 137:
                pedidos = len(client.pedidos)
                await rec.rodada()
                self.assertEqual(len(client.pedidos), pedidos + 1)
                canal = await self.estado.canal(CANAL_ID)
                if canal["erro"] is not None:
                    self.assertGreaterEqual(canal["proxima"], agora + 120)
                    esperas.append(canal["proxima"] - agora)
                    client.na_janela = 0
                agora = canal["proxima"]
        self.assertEqual(client.confirmados, list(range(1, 138)))
        self.assertEqual(len(client.pedidos), 150)  # 137 páginas + 13 FloodWait
        self.assertEqual(client.pedidos[11][0], 11)  # não retomar os dez IDs já confirmados
        self.assertTrue(all(limite == 100 and offset == -100 for _, offset, limite in client.pedidos))
        self.assertEqual(len(esperas), 13)
        self.assertIsNone((await self.estado.canal(CANAL_ID))["limite"])
        self.assertEqual((await self.estado.resumo())["ofertas"], {"pendente": 137})

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; contrato raw necessário")
    async def test_raw_tombstones_avancam_cobertura_sem_fabricar_eventos(self) -> None:
        from telethon.tl.types import MessageEmpty

        await self.preparar_historico(150)
        client = cliente_historico()
        client.historico[:100] = [MessageEmpty(id=i, peer_id=None) for i in range(1, 101)]
        rec = Recuperacao(self.estado, self.repo, Telegram(client, self.estado), Config(), asyncio.Event())
        self.assertEqual(await rec.rodada(), 0)
        canal = await self.estado.canal(CANAL_ID)
        self.assertEqual((canal["cursor"], canal["limite"]), (100, 150))
        self.assertEqual(len(client.requisicoes), 1)
        self.assertEqual((await self.estado.resumo())["ofertas"], {})
        await self.estado.acordar_canais()
        self.assertEqual(await rec.rodada(), 37)
        canal = await self.estado.canal(CANAL_ID)
        self.assertEqual((canal["cursor"], canal["limite"]), (137, 150))
        await self.estado.acordar_canais()
        self.assertEqual(await rec.rodada(), 0)
        canal = await self.estado.canal(CANAL_ID)
        self.assertEqual((canal["cursor"], canal["limite"]), (150, None))
        self.assertEqual(client.requisicoes, [(0, -100, 100), (101, -100, 100), (138, -100, 100)])
        self.assertIsNone(await self.estado.evento(CANAL_ID, 100))
        self.assertIsNotNone(await self.estado.evento(CANAL_ID, 101))

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; contrato raw necessário")
    async def test_raw_bootstrap_data_snapshot_superior_e_texto_formatado(self) -> None:
        from telethon.tl.types import MessageEntityCode

        client = cliente_historico()
        for msg in client.historico:
            msg.id += 1000
        client.historico[0].date = DATA - timedelta(days=2)
        client.historico[1].message = "CUPOM123"
        client.historico[1].entities = [MessageEntityCode(offset=0, length=8)]
        await self.estado.configurar_canal(CANAL_ID, "canal", 1, DATA.timestamp() - 86400)
        await self.estado.iniciar_varredura(CANAL_ID, 1050)
        canal = await self.estado.canal(CANAL_ID)
        original = dict(canal)
        pagina = await Telegram(client, self.estado).pagina(canal, 200)
        mensagens, esgotou = pagina
        self.assertEqual(canal, original, "O adaptador não pode alterar o snapshot do chamador")
        self.assertEqual([m.msg_id for m in mensagens], list(range(1002, 1051)))
        self.assertEqual(mensagens[0].texto, "`CUPOM123`")
        self.assertTrue(esgotou)
        self.assertEqual(pagina.cursor, 1050)
        self.assertEqual(client.requisicoes, [(0, -100, 100)])

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; contrato raw necessário")
    async def test_raw_resposta_ambigua_nao_equivale_a_pagina_vazia(self) -> None:
        from telethon.tl.types.messages import MessagesNotModified

        await self.preparar_historico(137)
        base = type(cliente_historico())

        class ClienteAmbiguo(base):
            async def __call__(self, request, *args, **kwargs):
                await super().__call__(request, *args, **kwargs)
                return MessagesNotModified(count=137)

        client = ClienteAmbiguo()
        rec = Recuperacao(self.estado, self.repo, Telegram(client, self.estado), Config(), asyncio.Event())
        self.assertEqual(await rec.rodada(), 0)
        canal = await self.estado.canal(CANAL_ID)
        self.assertEqual((canal["cursor"], canal["limite"]), (0, 137))
        self.assertEqual(canal["erro"], "ValueError")
        self.assertEqual(len(client.requisicoes), 1)

    async def test_migracao_aditiva_v3_preserva_jobs_midias_e_fronteira(self) -> None:
        await self.estado.configurar_canal(CANAL_ID, "canal", 1, 123)
        await self.estado.iniciar_varredura(CANAL_ID, 10)
        await self.estado.registrar_pagina(CANAL_ID, [self.mensagem(1)], 1, False, 0)
        job = await self.estado.obter_oferta(time.time(), True)
        await self.estado.finalizar_oferta(job, "aprovada", 42, midia=True)
        await self.estado.atualizar_midia(42, estado="retry", compensar=1, falha_apos_limpeza="ErroPermanente")
        evento, midia = await self.estado.evento(CANAL_ID, 1), await self.estado.midia(42)

        def schema_v3():
            with self.estado.db:
                self.estado.db.execute("DROP TABLE resolucoes")
                self.estado.db.execute("ALTER TABLE canais DROP COLUMN geracao")
                self.estado.db.execute("PRAGMA user_version=3")

        await self.estado._executar(schema_v3)
        await self.reiniciar()
        self.assertEqual(await self.estado.evento(CANAL_ID, 1), evento)
        self.assertEqual(await self.estado.midia(42), midia)
        canal = await self.estado.canal(CANAL_ID)
        self.assertEqual((canal["cursor"], canal["limite"], canal["bootstrap"]), (1, 10, 123))
        versao = await self.estado._executar(lambda: self.estado.db.execute("PRAGMA user_version").fetchone()[0])
        self.assertEqual(versao, 4)
        await self.estado.falhar_resolucao("@CANAL", time.time() + 120, "FloodWait")
        self.assertEqual((await self.estado.resolucao("canal"))["tentativas"], 1)

    @unittest.skipUnless(TEM_TELETHON, "Telethon não instalado; iterador real necessário")
    async def test_sdk_lacunas_pagina_exata_e_bootstrap_vazio(self) -> None:
        for ids, limite in (([3 * n for n in range(1, 138)], 500), (list(range(1, 101)), 100), ([], 50)):
            with self.subTest(total=len(ids)):
                # Cada caso usa outro canal local para não reutilizar a fronteira.
                local_id = CANAL_ID - len(ids)
                await self.estado.configurar_canal(local_id, "canal", 1, DATA.timestamp() - 86400)
                await self.estado.ativar_canais([local_id])
                await self.estado.iniciar_varredura(local_id, limite)
                client = cliente_historico()
                modelo = client.historico[0]
                from telethon.tl.types import Message
                client.historico = [Message(id=i, peer_id=modelo.peer_id, date=DATA, message="teste") for i in ids]
                tg = Telegram(client, self.estado)
                rec = Recuperacao(self.estado, self.repo, tg, Config(), asyncio.Event())
                for _ in range(4):
                    await self.estado.acordar_canais()
                    await rec.rodada()
                    if (await self.estado.canal(local_id))["limite"] is None:
                        break
                canal = await self.estado.canal(local_id)
                self.assertEqual(canal["cursor"], limite)
                self.assertIsNone(canal["limite"])
                for msg_id in ids:
                    self.assertIsNotNone(await self.estado.evento(local_id, msg_id))
