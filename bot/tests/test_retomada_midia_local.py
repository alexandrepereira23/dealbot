"""Retomada no pipeline ativo com SQLite real e fronteiras de mídia/RPC falsas.

Não prova conversão, atomicidade de disco nem isolamento Postgres. As barreiras
interrompem o fluxo real entre intenção, publicação, envio e vínculo duráveis.
"""

import asyncio
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cenarios_identidade import (
    RepositorioIdentidadeFake, ResolvedorFake, StorageFake, TelegramFake,
    aguardar, mensagem_sintetica,
)
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.midia import ArmazenamentosMidia
from src.modelos import FalhaLocal
from src.pipeline_identidade import PipelineIdentidade


class StorageProibido:
    async def enviar(self, chave, dados):
        raise AssertionError("storage_nao_deve_receber_job_local")

    async def remover(self, chave):
        raise AssertionError("storage_nao_deve_remover_job_local")

    async def url_publica(self, chave):
        raise AssertionError("storage_nao_deve_resolver_job_local")


class MidiaLocalFake:
    """Modela somente o contrato do adaptador, sem simular bytes WebP reais."""

    def __init__(self):
        self.finais = {}
        self.conversoes = 0
        self.consultas = []
        self.removidos = []

    async def publicada(self, chave):
        self.consultas.append(chave)
        return chave in self.finais

    async def url_publica(self, chave):
        return f"/media/{chave}"

    async def enviar(self, chave, dados):
        if chave not in self.finais:
            self.conversoes += 1
            self.finais[chave] = bytes(dados)
        return await self.url_publica(chave)

    async def remover(self, chave):
        self.finais.pop(chave, None)
        self.removidos.append(chave)


class TestRetomadaMidiaLocal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="retomada-midia-local-")
        self.raiz = Path(self.tmp.name)
        self.config = replace(Config(), state_dir=self.raiz / "estado",
            midia_modo="local", midia_local_dir=self.raiz / "midia",
            retry_base=.01, retry_max=.02, shutdown_timeout=.05)
        self.estado = EstadoLocal(self.config.state_dir)
        await self.estado.abrir()
        self.repo = RepositorioIdentidadeFake()
        self.local = MidiaLocalFake()
        self.destinos = ArmazenamentosMidia(StorageProibido(), self.local)
        self.telegram = TelegramFake()
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.pipeline = self.criar_pipeline()

    def criar_pipeline(self):
        return PipelineIdentidade(self.estado, self.repo, self.destinos,
            self.telegram, self.cache, self.config, resolvedor=ResolvedorFake())

    async def asyncTearDown(self):
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def agendar(self):
        mensagem = mensagem_sintetica(foto=True)
        await self.estado.registrar(mensagem)
        await self.pipeline._oferta(await self.estado.obter_oferta(time.time(), True))
        self.evento = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
        self.produto_id = self.evento["produto_id"]
        self.assertIsNotNone(self.evento["disponibilizado_em"])
        self.assertIsNone(self.repo.cards[self.produto_id]["foto_url"])
        self.assertEqual(self.telegram.chamadas, 0, "Oferta não baixa imagem")
        self.assertEqual(self.local.conversoes, 0)
        self.assertIsNone(await self.estado.obter_confirmacao())
        return await self.estado.obter_midia(time.time())

    async def reiniciar(self):
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.estado = EstadoLocal(self.config.state_dir)
        await self.estado.abrir()
        # Reverter o modo de escrita não pode redirecionar o job já agendado.
        self.config = replace(self.config, midia_modo="supabase")
        self.pipeline = self.criar_pipeline()

    async def conferir_pronta(self, original, *, ack_confirmado=False):
        final = await self.estado.midia(self.produto_id)
        self.assertEqual(final["estado"], "pronta")
        self.assertEqual(final["compensar"], 0)
        for campo in ("produto_id", "canal_id", "msg_id", "chave", "destino"):
            self.assertEqual(final[campo], original[campo])
        self.assertEqual(final["destino"], "local")
        self.assertEqual(final["url"], f"/media/{original['chave']}")
        self.assertEqual(self.repo.cards[self.produto_id]["foto_url"], final["url"])
        self.assertEqual(self.local.finais, {original["chave"]: b"foto_sintetica"})
        self.assertEqual(self.local.removidos, [])
        self.assertEqual(self.repo.chamadas["reservar_remocao"], 0)
        self.assertEqual(self.repo.chamadas["confirmar_remocao"], 0)
        self.assertEqual(self.repo.reservas, set())
        self.assertEqual(len(self.repo.cards), 1)
        self.assertEqual(len(self.repo.aparicoes), 1)
        evento = await self.estado.evento(original["canal_id"], original["msg_id"])
        for campo in ("produto_id", "decisao", "identidade", "hash"):
            self.assertEqual(evento[campo], self.evento[campo])
        ack = await self.estado.obter_confirmacao()
        if ack_confirmado:
            self.assertIsNone(ack)
            self.assertEqual(evento["remoto_confirmado"], 1)
            self.assertIn((original["canal_id"], original["msg_id"]), self.repo.confirmados)
        else:
            self.assertIsNotNone(ack)
            await self.repo.confirmar_evento(ack)
            await self.estado.confirmar_remoto(ack)
        self.assertIsNone(await self.estado.obter_confirmacao())

    async def interromper_e_retomar(self, checkpoint):
        job = await self.agendar()
        atingiu = asyncio.Event()

        async def barreira():
            atingiu.set()
            await asyncio.Event().wait()

        enviar = self.local.enviar
        atualizar = self.estado.atualizar_midia
        vincular = self.repo.vincular_foto

        async def enviar_interrompido(chave, dados):
            if checkpoint == "antes_publicar":
                await barreira()
            url = await enviar(chave, dados)
            if checkpoint == "apos_publicar":
                await barreira()
            return url

        async def atualizar_interrompido(produto_id, **campos):
            if checkpoint == "antes_intencao" and campos == {"compensar": 1}:
                await barreira()
            if checkpoint == "antes_enviado" and campos.get("enviado") == 1:
                await barreira()
            await atualizar(produto_id, **campos)
            if checkpoint == "apos_enviado" and campos.get("enviado") == 1:
                await barreira()
            if checkpoint == "apos_finalizacao" and campos.get("estado") == "pronta":
                await barreira()

        async def vincular_interrompido(produto_id, url):
            if checkpoint == "antes_vinculo":
                await barreira()
            resultado = await vincular(produto_id, url)
            if checkpoint == "apos_commit":
                await barreira()
            return resultado

        with patch.object(self.local, "enviar", side_effect=enviar_interrompido), \
             patch.object(self.estado, "atualizar_midia", side_effect=atualizar_interrompido), \
             patch.object(self.repo, "vincular_foto", side_effect=vincular_interrompido):
            tarefa = asyncio.create_task(self.pipeline._midia(job))
            try:
                await asyncio.wait_for(atingiu.wait(), 3)
                if checkpoint != "apos_finalizacao":
                    self.assertIsNone(await self.estado.obter_confirmacao())
                    self.assertEqual((await self.estado.limpar(time.time() + 100))["eventos"], 0)
            finally:
                tarefa.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tarefa

        publicado = job["chave"] in self.local.finais
        downloads = self.telegram.chamadas
        vinculos = self.repo.chamadas["vincular_foto"]
        await self.reiniciar()
        retomada = await self.estado.obter_midia(time.time())
        if checkpoint == "apos_finalizacao":
            self.assertIsNone(retomada)
        else:
            self.assertIsNotNone(retomada)
            await self.pipeline._midia(retomada)
            if not publicado and checkpoint == "antes_publicar":
                # Intenção existe, mas a prova de ausência não cria tombstone.
                self.assertEqual(self.repo.reservas, set())
                await self.pipeline._midia(await self.estado.obter_midia(time.time()))
        self.assertEqual(self.telegram.chamadas, downloads + int(not publicado))
        self.assertEqual(self.local.conversoes, 1)
        if checkpoint in {"apos_commit", "apos_finalizacao"}:
            self.assertEqual(self.repo.chamadas["vincular_foto"], vinculos)
        await self.conferir_pronta(job)

    async def test_restart_antes_da_intencao(self):
        await self.interromper_e_retomar("antes_intencao")

    async def test_restart_com_intencao_antes_da_publicacao(self):
        await self.interromper_e_retomar("antes_publicar")

    async def test_restart_apos_publicacao_antes_da_resposta(self):
        await self.interromper_e_retomar("apos_publicar")

    async def test_restart_antes_do_checkpoint_enviado(self):
        await self.interromper_e_retomar("antes_enviado")

    async def test_restart_apos_checkpoint_enviado(self):
        await self.interromper_e_retomar("apos_enviado")

    async def test_restart_antes_do_vinculo(self):
        await self.interromper_e_retomar("antes_vinculo")

    async def test_restart_apos_commit_com_resposta_perdida(self):
        await self.interromper_e_retomar("apos_commit")

    async def test_restart_apos_finalizacao_duravel(self):
        await self.interromper_e_retomar("apos_finalizacao")

    async def test_worker_reconcilia_timeout_apos_commit_do_vinculo(self):
        job = await self.agendar()
        await self.estado.atualizar_midia(self.produto_id, estado="retry")
        vincular = self.repo.vincular_foto

        async def vincular_sem_resposta(produto_id, url):
            await vincular(produto_id, url)
            raise TimeoutError("resposta_perdida_apos_commit")

        with patch.object(self.repo, "vincular_foto", side_effect=vincular_sem_resposta):
            self.pipeline.iniciar()

            async def pronta():
                return (await self.estado.midia(self.produto_id))["estado"] == "pronta"

            await aguardar(pronta, pipeline=self.pipeline)
            await self.pipeline.encerrar()
        self.assertEqual(self.repo.chamadas["vincular_foto"], 1)
        self.assertEqual(self.telegram.chamadas, 1)
        self.assertEqual(self.local.conversoes, 1)
        # O worker de acks pode ter confirmado antes deste ponto.
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        await self.conferir_pronta(job, ack_confirmado=bool(evento["remoto_confirmado"]))

    async def test_wrapper_ativo_reconhece_publicacao_do_destino_congelado(self):
        job = await self.agendar()
        await self.local.enviar(job["chave"], b"foto_sintetica")
        self.assertTrue(await self.pipeline._publicacao_local_conhecida(job))
        self.assertEqual(self.local.consultas, [job["chave"]])

    async def test_publicacao_recuperavel_precede_falha_terminal(self):
        job = await self.agendar()
        await self.local.enviar(job["chave"], b"foto_sintetica")
        await self.estado.atualizar_midia(self.produto_id, compensar=1,
            falha_apos_limpeza="ErroHTTPRemoto:422")
        await self.reiniciar()
        await self.pipeline._midia(await self.estado.obter_midia(time.time()))
        self.assertEqual(self.telegram.chamadas, 0)
        await self.conferir_pronta(job)

    async def test_destino_local_indisponivel_preserva_pendencia_no_worker(self):
        job = await self.agendar()
        await self.estado.atualizar_midia(self.produto_id, compensar=1, estado="retry")
        self.destinos.local = None
        self.pipeline.iniciar()

        async def falhou():
            atual = await self.estado.midia(self.produto_id)
            return atual["erro"] is not None

        await aguardar(falhou, pipeline=self.pipeline)
        await self.pipeline.encerrar()
        atual = await self.estado.midia(self.produto_id)
        self.assertEqual(atual["estado"], "retry")
        self.assertIsNone(atual["finalizado_em"])
        self.assertEqual(atual["compensar"], 1)
        self.assertEqual(atual["chave"], job["chave"])
        self.assertEqual(self.telegram.chamadas, 0)
        self.assertEqual(self.repo.reservas, set())

    async def encerrar_na_barreira(self, classe, reivindicado, liberar, *, repetidos=False):
        encerrando = None
        self.pipeline.iniciar()
        try:
            await asyncio.wait_for(reivindicado.wait(), 3)
            worker = next(t for t in self.pipeline.tasks if t.get_name() == f"{classe}-0")
            encerrando = asyncio.create_task(self.pipeline.encerrar())

            async def cancelamento_pedido():
                while not worker.cancelling():
                    await asyncio.sleep(.001)
            await asyncio.wait_for(cancelamento_pedido(), 3)
            if repetidos:
                for _ in range(2):
                    worker.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(worker.done(), "claim em curso continua pertencendo ao worker")
                controles = [t for t in self.pipeline._controles if not t.done()]
                do_worker = [t for t in controles if t.get_name() == worker.get_name()]
                self.assertEqual(len(do_worker), 1)
                self.assertIsNot(do_worker[0], worker)
                self.assertLessEqual(len(controles), self.config.oferta_workers + self.config.midia_workers)
            liberar.set()
            await asyncio.wait_for(encerrando, 3)
        finally:
            liberar.set()
            if encerrando is not None:
                await asyncio.gather(encerrando, return_exceptions=True)
        self.assertFalse(self.pipeline._controles)

    async def conferir_cancelamento_durante_claim(self, classe, *, repetidos=False):
        # Um commit já pode ter reivindicado o job, embora o await ainda não
        # tenha retornado ao worker. A barreira força essa janela sem lentidão
        # real, sem alterar o watchdog ou synchronous=FULL.
        self.config = replace(self.config, oferta_workers=1, midia_workers=1)
        self.pipeline = self.criar_pipeline()
        if classe == "midia":
            original = await self.agendar()
            await self.estado.atualizar_midia(self.produto_id, estado="retry")
            nome = "obter_midia"
        else:
            msg = mensagem_sintetica(foto=True)
            await self.estado.registrar(msg)
            original = {"canal_id": msg.canal_id, "msg_id": msg.msg_id}
            nome = "obter_oferta"
        obter = getattr(self.estado, nome)
        reivindicado, liberar = asyncio.Event(), asyncio.Event()

        async def obter_com_barreira(*args):
            job = await obter(*args)
            if job is not None:
                reivindicado.set()
                await liberar.wait()
            return job

        with patch.object(self.estado, nome, side_effect=obter_com_barreira):
            await self.encerrar_na_barreira(classe, reivindicado, liberar, repetidos=repetidos)
        if classe == "midia":
            final = await self.estado.midia(original["produto_id"])
            self.assertEqual(final["chave"], original["chave"])
            self.assertEqual(final["destino"], original["destino"])
        else:
            final = await self.estado.evento(original["canal_id"], original["msg_id"])
        self.assertEqual(final["estado"], "retry", "encerrar deve devolver inclusive claim cujo await não retornou")
        self.assertIsNone(final["finalizado_em"])
        self.assertEqual(self.telegram.chamadas, 0)
        self.assertEqual(self.local.conversoes, 0)
        self.assertEqual(self.repo.reservas, set())
        self.assertTrue(all(t.done() for t in self.pipeline.tasks))
        self.assertFalse(self.pipeline._controles)

    async def test_encerramento_devolve_claim_de_midia_ainda_sem_retorno(self):
        await self.conferir_cancelamento_durante_claim("midia")

    async def test_encerramento_devolve_claim_de_oferta_ainda_sem_retorno(self):
        await self.conferir_cancelamento_durante_claim("oferta")

    async def test_cancelamentos_repetidos_na_aquisicao_nao_perdem_claim_nem_acumulam_controles(self):
        await self.conferir_cancelamento_durante_claim("midia", repetidos=True)

    async def test_cancelamento_no_tratamento_do_erro_tambem_devolve_claim(self):
        await self.agendar()
        await self.estado.atualizar_midia(self.produto_id, compensar=1, estado="retry")
        self.destinos.local = None
        iniciou, liberar = asyncio.Event(), asyncio.Event()
        consultar = self.estado.midia

        async def consulta_com_barreira(produto_id):
            if asyncio.current_task().get_name() == "midia-0":
                iniciou.set()
                await liberar.wait()
            return await consultar(produto_id)

        with patch.object(self.estado, "midia", side_effect=consulta_com_barreira):
            await self.encerrar_na_barreira("midia", iniciou, liberar)
        final = await consultar(self.produto_id)
        self.assertEqual(final["estado"], "retry")
        self.assertIsNone(final["finalizado_em"])
        self.assertEqual(final["compensar"], 1)
        self.assertEqual(self.telegram.chamadas, 0)
        self.assertEqual(self.repo.reservas, set())

    async def test_falha_local_ao_drenar_claim_sobe_ao_supervisor(self):
        iniciou, liberar = asyncio.Event(), asyncio.Event()
        erro = FalhaLocal("falha_claim_sintetica")

        async def claim_falho(agora):
            iniciou.set()
            await liberar.wait()
            raise erro

        with patch.object(self.estado, "obter_midia", side_effect=claim_falho), \
             patch.object(self.pipeline, "_devolver", side_effect=AssertionError("nao_inventar_job")):
            await self.encerrar_na_barreira("midia", iniciou, liberar)
        self.assertTrue(self.pipeline.fatal.done())
        self.assertIs(self.pipeline.fatal.result(), erro)

    async def test_claim_vazio_cancelado_nao_inventa_devolucao(self):
        iniciou, liberar = asyncio.Event(), asyncio.Event()

        async def sem_job(agora):
            iniciou.set()
            await liberar.wait()
            return None

        with patch.object(self.estado, "obter_midia", side_effect=sem_job), \
             patch.object(self.pipeline, "_devolver", side_effect=AssertionError("nao_inventar_job")):
            await self.encerrar_na_barreira("midia", iniciou, liberar, repetidos=True)
        self.assertFalse(self.pipeline.fatal.done())

    async def test_cancelamentos_repetidos_na_devolucao_aguardam_retry_duravel(self):
        original = await self.agendar()
        await self.estado.atualizar_midia(self.produto_id, estado="retry")
        processamento, iniciou, liberar = asyncio.Event(), asyncio.Event(), asyncio.Event()
        devolver = self.pipeline._devolver

        async def processar(job):
            processamento.set()
            await asyncio.Event().wait()

        async def devolver_com_barreira(classe, job):
            iniciou.set()
            await liberar.wait()
            await devolver(classe, job)

        encerrando = None
        with patch.object(self.pipeline, "_midia", side_effect=processar), \
             patch.object(self.pipeline, "_devolver", side_effect=devolver_com_barreira):
            self.pipeline.iniciar()
            try:
                await asyncio.wait_for(processamento.wait(), 3)
                encerrando = asyncio.create_task(self.pipeline.encerrar())
                await asyncio.wait_for(iniciou.wait(), 3)
                worker = next(t for t in self.pipeline.tasks if t.get_name() == "midia-0")
                for _ in range(2):
                    worker.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(worker.done())
                self.assertFalse(encerrando.done())
                controles = [t for t in self.pipeline._controles if not t.done()]
                do_worker = [t for t in controles if t.get_name() == worker.get_name()]
                self.assertEqual(len(do_worker), 1)
                self.assertIsNot(do_worker[0], worker)
                self.assertLessEqual(len(controles), self.config.oferta_workers + self.config.midia_workers)
                self.assertEqual((await self.estado.midia(self.produto_id))["estado"], "processando")
                liberar.set()
                await asyncio.wait_for(encerrando, 3)
            finally:
                liberar.set()
                if encerrando is not None:
                    await asyncio.gather(encerrando, return_exceptions=True)
        final = await self.estado.midia(self.produto_id)
        self.assertEqual(final["estado"], "retry")
        self.assertEqual(final["chave"], original["chave"])
        self.assertIsNone(final["finalizado_em"])
        self.assertFalse(self.pipeline._controles)

    async def test_falha_local_ao_devolver_nao_finge_retry_gravado(self):
        original = await self.agendar()
        await self.estado.atualizar_midia(self.produto_id, estado="retry")
        obter = self.estado.obter_midia
        iniciou, liberar = asyncio.Event(), asyncio.Event()
        erro = FalhaLocal("falha_devolucao_sintetica")

        async def obter_com_barreira(agora):
            job = await obter(agora)
            if job is not None:
                iniciou.set()
                await liberar.wait()
            return job

        with patch.object(self.estado, "obter_midia", side_effect=obter_com_barreira), \
             patch.object(self.pipeline, "_devolver", side_effect=erro):
            await self.encerrar_na_barreira("midia", iniciou, liberar)
        self.assertTrue(self.pipeline.fatal.done())
        self.assertIs(self.pipeline.fatal.result(), erro)
        final = await self.estado.midia(self.produto_id)
        self.assertEqual(final["estado"], "processando", "falha local exige recuperação, não sucesso fictício")
        self.assertEqual(final["chave"], original["chave"])

    async def test_adaptador_sem_prova_nao_significa_publicacao_ausente(self):
        job = await self.agendar()
        self.destinos.local = StorageFake()  # Não implementa publicada.
        with self.assertRaisesRegex(RuntimeError, "publicacao_local_indisponivel"):
            await self.pipeline._publicacao_local_conhecida(job)

    async def test_erro_de_inspecao_nao_baixa_nem_compensa(self):
        job = await self.agendar()
        await self.estado.atualizar_midia(self.produto_id, compensar=1)
        await self.reiniciar()
        with patch.object(self.local, "publicada", side_effect=OSError("final_incompativel")):
            with self.assertRaisesRegex(OSError, "final_incompativel"):
                await self.pipeline._midia(await self.estado.obter_midia(time.time()))
        atual = await self.estado.midia(self.produto_id)
        self.assertEqual(atual["compensar"], 1)
        self.assertIsNone(atual["finalizado_em"])
        self.assertEqual(self.telegram.chamadas, 0)
        self.assertEqual(self.repo.reservas, set())

    async def test_tombstone_preexistente_nao_e_retirado_para_forcar_vinculo(self):
        job = await self.agendar()
        url = await self.local.enviar(job["chave"], b"foto_sintetica")
        self.repo.reservas.add(url)
        await self.estado.atualizar_midia(self.produto_id, compensar=1)
        await self.reiniciar()
        await self.pipeline._midia(await self.estado.obter_midia(time.time()))
        self.assertIsNone(self.repo.cards[self.produto_id]["foto_url"])
        self.assertEqual(self.repo.reservas, {url})
        self.assertEqual(self.repo.remocoes, {url})
        self.assertEqual(self.local.removidos, [job["chave"]])
        self.assertEqual(self.telegram.chamadas, 0)
        self.assertEqual(self.local.conversoes, 1)

    async def test_compensacao_conserva_reserva_remocao_e_ack(self):
        job = await self.agendar()
        url = await self.local.enviar(job["chave"], b"foto_sintetica")
        await self.estado.atualizar_midia(self.produto_id, enviado=1, url=url, compensar=1)
        self.repo.cards[self.produto_id]["removido"] = True
        await self.reiniciar()
        await self.pipeline._midia(await self.estado.obter_midia(time.time()))
        self.assertEqual((await self.estado.midia(self.produto_id))["estado"], "removida")
        self.assertEqual(self.local.removidos, [job["chave"]])
        self.assertEqual(self.repo.reservas, {url})
        self.assertEqual(self.repo.remocoes, {url})
        self.assertEqual(self.repo.chamadas["reservar_remocao"], 1)
        self.assertEqual(self.repo.chamadas["confirmar_remocao"], 1)


if __name__ == "__main__":
    unittest.main()
