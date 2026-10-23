"""Exercita processos Linux locais; não acessa Telegram, Supabase nem VPS."""

import asyncio
import signal
import sys
import tempfile
import unittest


@unittest.skipIf(sys.platform == "win32", "Sinais POSIX são verificados em Python Linux/WSL")
class TestSinais(unittest.IsolatedAsyncioTestCase):
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
                segundo = await asyncio.create_subprocess_exec(sys.executable, "-S", "-m", "tests.processo_falso",
                    diretorio, "segundo", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    saida, erros = await asyncio.wait_for(segundo.communicate(), 45)
                    self.assertEqual(segundo.returncode, 0, erros.decode())
                    self.assertIn(b"retomado:1", saida)
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
