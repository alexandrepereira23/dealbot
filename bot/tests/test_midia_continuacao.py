"""V-007: cursor limitado; só a ordem de enumeração é controlada.

Stat, abertura, locks e remoção usam arquivos temporários e syscalls reais.
"""

import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.midia import ArmazenamentoLocal, TEMP_PREFIXO
from src.midia_arquivos import DiretorioMidiaSeguro


class TestContinuacaoTemporarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dealbot-continuacao-")
        self.raiz = Path(self.tmp.name) / "midia"
        self.raiz.mkdir()
        self.midia = self.adaptador()
        self.agora = time.time()

    def adaptador(self):
        return ArmazenamentoLocal(self.raiz, max_entrada=1000, max_pixels=100,
                                  lado_max=10, max_saida=1000, workers=2)

    async def asyncTearDown(self):
        await self.midia.fechar()
        self.tmp.cleanup()

    def arquivo(self, nome, *, antigo=True):
        caminho = self.raiz / nome
        caminho.write_bytes(b"conteudo-sintetico")
        instante = self.agora - 90000 if antigo else self.agora
        os.utime(caminho, (instante, instante))
        return caminho

    def enumeracao(self, nomes):
        self.aberturas, self.fechadas, self.visitados = [], [], []

        def listar(raiz):
            self.aberturas.append(raiz)
            try:
                for nome in nomes:
                    self.visitados.append(nome)
                    yield nome
            finally:
                self.fechadas.append(raiz)

        return patch.object(DiretorioMidiaSeguro, "listar", listar)

    def conferir_fechadas(self):
        self.assertEqual(self.aberturas, self.fechadas)
        for raiz in self.aberturas:
            self.assertIsNone(raiz.fd)
            self.assertEqual(raiz._handles, [])
        self.assertIsNone(self.midia._raiz_limpeza)
        self.assertIsNone(self.midia._entradas_limpeza)

    async def limpar(self, **opcoes):
        return await self.midia.limpar_temporarios(agora=self.agora, **opcoes)

    async def test_prefixo_permanente_avanca_sem_prefetch_e_reabre_apos_eof(self):
        finais = [self.arquivo(f"{n:032x}.webp") for n in range(2)]
        temporario = self.arquivo(f"{TEMP_PREFIXO}abandonado.tmp")
        nomes = [p.name for p in finais] + [temporario.name]
        with self.enumeracao(nomes):
            removidos = [await self.limpar(exame=2) for _ in range(2)]
            self.assertEqual(removidos, [0, 1])
            self.assertEqual(self.visitados, nomes, "nenhum prefixo reexaminado ou prefetch")
            self.assertFalse(temporario.exists())
            self.conferir_fechadas()
            self.assertEqual(await self.limpar(exame=2), 0)
            self.assertEqual(self.visitados, nomes + nomes[:2])
            self.assertEqual(len(self.aberturas), 2)
            await self.midia.fechar()
            self.conferir_fechadas()
        for final in finais:
            self.assertEqual(final.read_bytes(), b"conteudo-sintetico")

    async def test_limite_de_remocao_nao_consume_proximo_nome(self):
        nomes = [self.arquivo(f"{TEMP_PREFIXO}{n}.tmp").name for n in range(3)]
        with self.enumeracao(nomes):
            for indice in range(3):
                self.assertEqual(await self.limpar(limite=1, exame=2), 1)
                self.assertEqual(self.visitados, nomes[:indice + 1])
            # EOF exatamente após um orçamento é descoberto só na chamada seguinte.
            self.assertEqual(await self.limpar(limite=1, exame=2), 0)
            self.assertEqual(len(self.aberturas), 1)
            self.conferir_fechadas()

    async def test_continuacao_preserva_final_recente_e_lock_fisico(self):
        final = self.arquivo("a" * 32 + ".webp")
        ativo = self.arquivo(f"{TEMP_PREFIXO}ativo.tmp")
        recente = self.arquivo(f"{TEMP_PREFIXO}recente.tmp", antigo=False)
        velho = self.arquivo(f"{TEMP_PREFIXO}velho.tmp")
        nomes = [p.name for p in (final, ativo, recente, velho)]
        with ativo.open("r+b") as escritor:
            self.midia._travar(escritor)
            try:
                with self.enumeracao(nomes):
                    self.assertEqual([await self.limpar(exame=2) for _ in range(3)], [0, 1, 0])
                    self.assertEqual(self.visitados, nomes)
                    self.conferir_fechadas()
                self.assertTrue(ativo.exists())
                self.assertTrue(recente.exists())
                self.assertTrue(final.exists())
                self.assertFalse(velho.exists())
            finally:
                self.midia._destravar(escritor)
        # Reinício perde somente o cursor volátil, não a capacidade de avançar.
        await self.midia.fechar()
        self.midia = self.adaptador()
        with self.enumeracao(nomes):
            self.assertEqual(await self.limpar(exame=2), 1)
            self.assertFalse(ativo.exists())
            await self.midia.fechar()
            self.conferir_fechadas()
        self.assertEqual(final.read_bytes(), b"conteudo-sintetico")
        self.assertTrue(recente.exists())

    async def test_scandir_real_fechado_em_eof_e_no_fechamento_do_adaptador(self):
        self.arquivo("a" * 32 + ".webp")
        listar = DiretorioMidiaSeguro.listar
        with patch.object(DiretorioMidiaSeguro, "listar", autospec=True, side_effect=listar):
            self.assertEqual(await self.limpar(exame=1), 0)
            raiz = self.midia._raiz_limpeza
            entradas = self.midia._entradas_limpeza
            self.assertIsNotNone(raiz)
            self.assertEqual(await self.limpar(exame=1), 0)
            self.assertIsNone(entradas.gi_frame)
            self.assertIsNone(raiz.fd)
            self.assertEqual(raiz._handles, [])
            self.assertIsNone(self.midia._raiz_limpeza)
            self.assertEqual(await self.limpar(exame=1), 0)
            raiz = self.midia._raiz_limpeza
            entradas = self.midia._entradas_limpeza
            await self.midia.fechar()
            await self.midia.fechar()
            self.assertIsNone(entradas.gi_frame)
            self.assertIsNone(raiz.fd)
            self.assertEqual(raiz._handles, [])
        # Em Windows isto também comprova liberação dos handles sem SHARE_DELETE.
        self.raiz.rename(self.raiz.with_name("midia-fechada"))

    async def test_erro_de_enumeracao_fecha_cursor_e_ancora_e_permite_novo_ciclo(self):
        final = self.arquivo("a" * 32 + ".webp")
        raizes, fechadas = [], []

        def listar(raiz):
            raizes.append(raiz)
            try:
                yield final.name
                raise OSError("enumeracao_sintetica")
            finally:
                fechadas.append(raiz)

        with patch.object(DiretorioMidiaSeguro, "listar", listar):
            self.assertEqual(await self.limpar(exame=1), 0)
            with self.assertRaisesRegex(OSError, "enumeracao_sintetica"):
                await self.limpar(exame=1)
            self.assertEqual(raizes, fechadas)
            self.assertIsNone(raizes[0].fd)
            self.assertEqual(raizes[0]._handles, [])
            self.assertIsNone(self.midia._raiz_limpeza)
            self.assertIsNone(self.midia._entradas_limpeza)
        velho = self.arquivo(f"{TEMP_PREFIXO}velho.tmp")
        self.assertEqual(await self.limpar(), 1)
        self.assertFalse(velho.exists())
        self.assertTrue(final.exists())

    async def test_workers_concorrentes_e_cancelamentos_preservam_cursor_unico(self):
        final = self.arquivo("a" * 32 + ".webp")
        velho = self.arquivo(f"{TEMP_PREFIXO}velho.tmp")
        iniciou, segundo_entrou = asyncio.Event(), asyncio.Event()
        liberar = threading.Event()
        loop = asyncio.get_running_loop()
        aberturas, visitados = [], []
        limpar = self.midia._limpar_temporarios

        def listar(raiz):
            aberturas.append(raiz)
            loop.call_soon_threadsafe(iniciou.set)
            if not liberar.wait(5):
                raise AssertionError("barreira_enumeracao")
            for nome in (final.name, velho.name):
                visitados.append(nome)
                yield nome

        def segunda(*args):
            loop.call_soon_threadsafe(segundo_entrou.set)
            return limpar(*args)

        tarefas = []
        with patch.object(DiretorioMidiaSeguro, "listar", listar):
            try:
                tarefas.append(asyncio.create_task(self.limpar(exame=1)))
                await asyncio.wait_for(iniciou.wait(), 3)
                tarefas[0].cancel()
                await asyncio.sleep(0)
                tarefas[0].cancel()
                with patch.object(self.midia, "_limpar_temporarios", side_effect=segunda):
                    tarefas.append(asyncio.create_task(self.limpar(exame=1)))
                    await asyncio.wait_for(segundo_entrou.wait(), 3)
                    self.assertFalse(tarefas[0].done())
                    self.assertFalse(tarefas[1].done())
                    self.assertEqual(len(aberturas), 1)
                    liberar.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(tarefas[0], 3)
                    self.assertEqual(await asyncio.wait_for(tarefas[1], 3), 1)
                self.assertEqual(visitados, [final.name, velho.name])
                self.assertEqual(len(aberturas), 1)
                self.assertEqual(await self.limpar(exame=1), 0)
                self.assertIsNone(self.midia._raiz_limpeza)
            finally:
                liberar.set()
                await asyncio.gather(*tarefas, return_exceptions=True)
        self.assertTrue(final.exists())
        self.assertFalse(velho.exists())

    @unittest.skipIf(os.name == "nt", "Windows prende a raiz contra renomeação")
    async def test_raiz_trocada_entre_ciclos_nao_redireciona_cursor(self):
        final = self.arquivo("a" * 32 + ".webp")
        velho = self.arquivo(f"{TEMP_PREFIXO}velho.tmp")
        with self.enumeracao([final.name, velho.name]):
            self.assertEqual(await self.limpar(exame=1), 0)
            antiga = self.raiz.with_name("midia-antiga")
            self.raiz.rename(antiga)
            fora = Path(self.tmp.name) / "fora"
            fora.mkdir()
            externo = fora / velho.name
            externo.write_bytes(b"externo-intocavel")
            os.utime(externo, (self.agora - 90000, self.agora - 90000))
            self.raiz.symlink_to(fora, target_is_directory=True)
            self.assertEqual(await self.limpar(exame=1), 1)
            self.assertFalse((antiga / velho.name).exists())
            self.assertEqual(externo.read_bytes(), b"externo-intocavel")
            self.assertEqual(await self.limpar(exame=1), 0)
            self.conferir_fechadas()
            with self.assertRaises(OSError):
                await self.limpar(exame=1)
            self.assertEqual(externo.read_bytes(), b"externo-intocavel")
