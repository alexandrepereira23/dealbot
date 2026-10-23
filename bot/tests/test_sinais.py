"""Exercita processos Linux locais; não acessa Telegram, Supabase nem VPS."""

import asyncio
import math
import signal
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, call, patch

from src.sinais import sinais_encerramento


class TestRegistroSinais(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = Mock()
        self.parar = Mock(spec=asyncio.Event)
        self.anteriores = {signal.SIGINT: Mock(), signal.SIGTERM: signal.SIG_IGN}
        self.addCleanup(patch.stopall)
        patch("src.sinais.asyncio.get_running_loop", return_value=self.loop).start()
        patch("src.sinais.signal.getsignal", side_effect=self.anteriores.__getitem__).start()
        self.instalar = patch("src.sinais.signal.signal").start()

    def conferir_restauracao(self) -> None:
        for sinal, anterior in self.anteriores.items():
            self.assertIn(call(sinal, anterior), self.instalar.call_args_list)

    def test_nativo_registra_remove_e_restaura_handlers(self) -> None:
        with sinais_encerramento(self.parar):
            self.assertEqual(self.loop.add_signal_handler.call_args_list,
                [call(signal.SIGINT, self.parar.set), call(signal.SIGTERM, self.parar.set)])
            self.instalar.assert_not_called()
        self.assertEqual(self.loop.remove_signal_handler.call_args_list,
            [call(signal.SIGTERM), call(signal.SIGINT)])
        self.conferir_restauracao()

    def test_fallback_agenda_no_loop_sem_set_direto_e_restaura(self) -> None:
        self.loop.add_signal_handler.side_effect = NotImplementedError
        with sinais_encerramento(self.parar):
            for sinal, handler in [chamada.args for chamada in self.instalar.call_args_list]:
                handler(sinal, None)
            self.parar.set.assert_not_called()
            self.assertEqual(self.loop.call_soon_threadsafe.call_args_list,
                [call(self.parar.set), call(self.parar.set)])
            self.loop.call_soon_threadsafe.call_args.args[0]()
            self.parar.set.assert_called_once_with()
        self.loop.remove_signal_handler.assert_not_called()
        self.conferir_restauracao()

    def test_modos_mistos_e_excecao_no_corpo_restauram(self) -> None:
        self.loop.add_signal_handler.side_effect = [None, NotImplementedError]
        with self.assertRaisesRegex(ValueError, "corpo"):
            with sinais_encerramento(self.parar):
                raise ValueError("corpo")
        self.loop.remove_signal_handler.assert_called_once_with(signal.SIGINT)
        self.conferir_restauracao()

    def test_falha_parcial_nao_aciona_fallback_e_remove_primeiro(self) -> None:
        self.loop.add_signal_handler.side_effect = [None, RuntimeError("registro")]
        with self.assertRaisesRegex(RuntimeError, "registro"):
            with sinais_encerramento(self.parar):
                self.fail("não deve entrar após falha de registro")
        self.loop.remove_signal_handler.assert_called_once_with(signal.SIGINT)
        self.assertEqual(self.instalar.call_count, 2)  # Só restauração, sem fallback.
        self.conferir_restauracao()

    def test_falha_ao_instalar_fallback_restaura_todos(self) -> None:
        self.loop.add_signal_handler.side_effect = NotImplementedError

        def instalar(sinal, handler):
            if sinal == signal.SIGTERM and handler != self.anteriores[sinal]:
                raise ValueError("fallback")

        self.instalar.side_effect = instalar
        with self.assertRaisesRegex(ValueError, "fallback"):
            with sinais_encerramento(self.parar):
                self.fail("não deve entrar após falha do fallback")
        self.conferir_restauracao()

    def test_erro_ao_remover_nao_impede_demais_restauracoes(self) -> None:
        self.loop.remove_signal_handler.side_effect = [RuntimeError("remover"), None]
        with self.assertRaisesRegex(RuntimeError, "remover"):
            with sinais_encerramento(self.parar):
                pass
        self.assertEqual(self.loop.remove_signal_handler.call_count, 2)
        self.conferir_restauracao()

    def test_exige_thread_principal_antes_de_instalar(self) -> None:
        erros = []

        def executar():
            try:
                with sinais_encerramento(self.parar):
                    pass
            except RuntimeError as erro:
                erros.append(str(erro))

        thread = threading.Thread(target=executar)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(erros, ["sinais_exigem_thread_principal"])
        self.loop.add_signal_handler.assert_not_called()
        self.instalar.assert_not_called()

    def test_exige_loop_em_execucao(self) -> None:
        with patch("src.sinais.asyncio.get_running_loop", side_effect=RuntimeError("sem_loop")):
            with self.assertRaisesRegex(RuntimeError, "sem_loop"):
                with sinais_encerramento(self.parar):
                    pass
        self.instalar.assert_not_called()


class TestOrcamentoEncerramento(unittest.IsolatedAsyncioTestCase):
    async def test_orcamento_limita_espera_nao_devolucao_apos_cancelamento(self) -> None:
        from src.config import Config
        from src.pipeline import Pipeline

        estado = Mock()
        estado.resumo = AsyncMock(return_value={})
        cfg = replace(Config(), shutdown_timeout=0.05)
        pipeline = Pipeline(estado, None, None, None, None, cfg)
        iniciou = asyncio.Event()

        async def worker():
            iniciou.set()
            try:
                await asyncio.Event().wait()
            finally:
                # Representa a devolução durável do claim após o cancelamento.
                await asyncio.sleep(0.08)

        tarefa = asyncio.create_task(worker())
        pipeline.tasks = [tarefa]
        await iniciou.wait()
        try:
            with patch("src.pipeline.asyncio.wait", wraps=asyncio.wait) as esperar:
                inicio = time.monotonic()
                await asyncio.wait_for(pipeline.encerrar(), 5)
                duracao = time.monotonic() - inicio
            esperar.assert_awaited_once_with([tarefa], timeout=0.05)
            self.assertTrue(tarefa.cancelled())
            self.assertGreater(duracao, cfg.shutdown_timeout + 0.06)
        finally:
            if not tarefa.done():
                tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)


@unittest.skipIf(sys.platform == "win32", "Sinais POSIX são verificados em Python Linux/WSL")
class TestSinais(unittest.IsolatedAsyncioTestCase):
    async def exercitar_ocioso(self, sinal: int, modo: str = "ocioso") -> None:
        processo = await asyncio.create_subprocess_exec(sys.executable, "-S", "-m", "tests.processo_falso",
            ".", modo, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            self.assertEqual(await asyncio.wait_for(processo.stdout.readline(), 20), b"pronto\n")
            processo.send_signal(sinal)
            saida, erros = await asyncio.wait_for(processo.communicate(), 5)
            self.assertEqual(processo.returncode, 0, erros.decode())
            self.assertEqual(saida, b"")
        finally:
            if processo.returncode is None:
                processo.kill()
                await processo.wait()

    async def exercitar(self, sinal: int) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            primeiro = await asyncio.create_subprocess_exec(sys.executable, "-S", "-m", "tests.processo_falso",
                diretorio, "primeiro", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                self.assertEqual(await asyncio.wait_for(primeiro.stdout.readline(), 20), b"pronto\n")
                primeiro.send_signal(sinal)
                await asyncio.wait_for(primeiro.wait(), 5)
                if sinal != signal.SIGKILL:
                    self.assertEqual(primeiro.returncode, 0, (await primeiro.stderr.read()).decode())
                    saida = (await primeiro.stdout.read()).decode()
                    medida = next(linha for linha in saida.splitlines() if linha.startswith("encerramento_s:"))
                    duracao = float(medida.split(":")[1])
                    self.assertTrue(math.isfinite(duracao))
                    self.assertGreaterEqual(duracao, 0.04)
                    # Não exige <= 0.05: cancelar/devolver SQLite também custa I/O.
                segundo = await asyncio.create_subprocess_exec(sys.executable, "-S", "-m", "tests.processo_falso",
                    diretorio, "segundo", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    saida, erros = await asyncio.wait_for(segundo.communicate(), 45)
                    self.assertEqual(segundo.returncode, 0, erros.decode())
                    self.assertIn(b"retomado:1", saida.splitlines())
                    self.assertIn(b"aparicoes:1", saida.splitlines())
                finally:
                    if segundo.returncode is None:
                        segundo.kill()
                        await segundo.wait()
            finally:
                if primeiro.returncode is None:
                    primeiro.kill()
                    await primeiro.wait()

    async def test_sigterm_durante_processamento_e_retomada(self) -> None:
        await self.exercitar(signal.SIGTERM)

    async def test_sigint_durante_processamento_e_retomada(self) -> None:
        await self.exercitar(signal.SIGINT)

    async def test_sigkill_claim_persistido_e_retomada(self) -> None:
        await self.exercitar(signal.SIGKILL)

    async def test_sigint_ocioso_sem_timer(self) -> None:
        await self.exercitar_ocioso(signal.SIGINT)

    async def test_sigterm_ocioso_sem_timer(self) -> None:
        await self.exercitar_ocioso(signal.SIGTERM)

    async def test_fallback_sigint_acorda_seletor_sem_timer(self) -> None:
        await self.exercitar_ocioso(signal.SIGINT, "fallback")

    async def test_fallback_sigterm_acorda_seletor_sem_timer(self) -> None:
        await self.exercitar_ocioso(signal.SIGTERM, "fallback")
