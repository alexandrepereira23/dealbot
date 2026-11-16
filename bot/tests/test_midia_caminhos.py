"""Corridas de caminho com arquivos próprios; não depende de Pillow/rede."""

import base64
import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.midia import ArmazenamentoLocal
from src.midia_arquivos import DiretorioMidiaSeguro


CHAVE = "a" * 32 + ".webp"
WEBP = base64.b64decode("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v02aAA=")


@unittest.skipIf(os.name == "nt", "Corridas com symlinks reais são exercitadas em POSIX")
class TestCaminhosMidiaPosix(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dealbot-caminhos-")
        self.base = Path(self.tmp.name)
        self.raiz = self.base / "midia"
        self.fora = self.base / "fora"
        self.fora.mkdir()
        self.midia = ArmazenamentoLocal(self.raiz, max_entrada=1000, max_pixels=100,
                                       lado_max=10, max_saida=1000)
        self.midia._abrir_diretorio()

    async def asyncTearDown(self) -> None:
        await self.midia.fechar()
        self.tmp.cleanup()

    def trocar_raiz(self) -> None:
        self.raiz.rename(self.base / "midia-antiga")
        self.raiz.symlink_to(self.fora, target_is_directory=True)

    async def test_troca_da_raiz_apos_stat_nao_remove_externo(self) -> None:
        (self.raiz / CHAVE).write_bytes(WEBP)
        externo = self.fora / CHAVE
        externo.write_bytes(b"externo-intocavel")
        original = DiretorioMidiaSeguro.stat

        def trocar(raiz: DiretorioMidiaSeguro, nome: str) -> os.stat_result:
            info = original(raiz, nome)
            self.trocar_raiz()
            return info

        with patch.object(DiretorioMidiaSeguro, "stat", trocar):
            await self.midia.remover(CHAVE)
        self.assertEqual(externo.read_bytes(), b"externo-intocavel")
        self.assertFalse((self.base / "midia-antiga" / CHAVE).exists())

    async def test_leitura_por_handle_nao_atravessa_raiz_trocada(self) -> None:
        (self.raiz / CHAVE).write_bytes(WEBP)
        (self.fora / CHAVE).write_bytes(b"fora")
        with DiretorioMidiaSeguro(self.raiz) as raiz:
            self.trocar_raiz()
            descritor = raiz.abrir(CHAVE, os.O_RDONLY)
            with os.fdopen(descritor, "rb") as arquivo:
                self.assertEqual(arquivo.read(), WEBP)
        with self.assertRaises(OSError):
            await self.midia.publicada(CHAVE)

    async def test_publicacao_e_temporario_ficam_no_handle_da_raiz(self) -> None:
        externo = self.fora / CHAVE
        externo.write_bytes(b"externo-intocavel")
        original = DiretorioMidiaSeguro.temporario

        def trocar(raiz: DiretorioMidiaSeguro, prefixo: str) -> tuple[int, str]:
            self.trocar_raiz()
            return original(raiz, prefixo)

        with patch.object(DiretorioMidiaSeguro, "temporario", trocar):
            await self.midia._executar(self.midia._publicar, CHAVE, WEBP)
        self.assertEqual(externo.read_bytes(), b"externo-intocavel")
        antiga = self.base / "midia-antiga"
        self.assertEqual((antiga / CHAVE).read_bytes(), WEBP)
        self.assertEqual(list(antiga.glob("*.tmp")), [])

    async def test_limpeza_temporaria_ancorada_nao_apaga_externo(self) -> None:
        nome = ".dealbot-media-abandonado.tmp"
        (self.raiz / nome).write_bytes(b"local")
        externo = self.fora / nome
        externo.write_bytes(b"externo-intocavel")
        instante = time.time()
        os.utime(self.raiz / nome, (instante - 90000, instante - 90000))
        original = DiretorioMidiaSeguro.stat

        def trocar(raiz: DiretorioMidiaSeguro, alvo: str) -> os.stat_result:
            info = original(raiz, alvo)
            self.trocar_raiz()
            return info

        with patch.object(DiretorioMidiaSeguro, "stat", trocar):
            self.assertEqual(await self.midia.limpar_temporarios(agora=instante), 1)
        self.assertEqual(externo.read_bytes(), b"externo-intocavel")

    async def test_ancestral_trocado_entre_aberturas_nao_redireciona_filho(self) -> None:
        ancestral = self.base / "pai"
        raiz = ancestral / "midia"
        raiz.mkdir(parents=True)
        (raiz / CHAVE).write_bytes(b"local")
        (self.fora / "midia").mkdir()
        externo = self.fora / "midia" / CHAVE
        externo.write_bytes(b"fora")
        original = os.open
        trocou = False

        def abrir(caminho: str | Path, flags: int, *args, **kwargs) -> int:
            nonlocal trocou
            if caminho == "midia" and not trocou:
                ancestral.rename(self.base / "pai-antigo")
                ancestral.symlink_to(self.fora, target_is_directory=True)
                trocou = True
            return original(caminho, flags, *args, **kwargs)

        with patch("src.midia_arquivos.os.open", side_effect=abrir):
            with DiretorioMidiaSeguro(raiz) as volume:
                with os.fdopen(volume.abrir(CHAVE, os.O_RDONLY), "rb") as arquivo:
                    self.assertEqual(arquivo.read(), b"local")
        self.assertTrue(trocou)
        self.assertEqual(externo.read_bytes(), b"fora")

    async def test_final_trocado_por_link_entre_stat_e_open_e_recusado(self) -> None:
        (self.raiz / CHAVE).write_bytes(WEBP)
        externo = self.fora / CHAVE
        externo.write_bytes(b"externo-intocavel")
        original = DiretorioMidiaSeguro.stat

        def trocar(raiz: DiretorioMidiaSeguro, nome: str) -> os.stat_result:
            info = original(raiz, nome)
            (self.raiz / nome).unlink()
            (self.raiz / nome).symlink_to(externo)
            return info

        with patch.object(DiretorioMidiaSeguro, "stat", trocar):
            with self.assertRaises(OSError):
                await self.midia.publicada(CHAVE)
        self.assertEqual(externo.read_bytes(), b"externo-intocavel")

    async def test_temporario_renomeado_e_substituido_nao_publica_link(self) -> None:
        externo = self.fora / "privado.webp"
        externo.write_bytes(b"externo-intocavel")
        original = DiretorioMidiaSeguro.publicar

        def trocar(raiz: DiretorioMidiaSeguro, temporario: str, final: str, descritor: int) -> None:
            caminho = self.raiz / temporario
            caminho.rename(caminho.with_name(temporario + ".guardado"))
            caminho.symlink_to(externo)
            original(raiz, temporario, final, descritor)

        with patch.object(DiretorioMidiaSeguro, "publicar", trocar):
            await self.midia._executar(self.midia._publicar, CHAVE, WEBP)
        self.assertFalse((self.raiz / CHAVE).is_symlink())
        self.assertEqual((self.raiz / CHAVE).read_bytes(), WEBP)
        self.assertEqual(externo.read_bytes(), b"externo-intocavel")

    async def test_temporario_desvinculado_nao_e_substituido_por_link_publicado(self) -> None:
        externo = self.fora / "privado.webp"
        externo.write_bytes(b"externo-intocavel")
        original = DiretorioMidiaSeguro.publicar

        def trocar(raiz: DiretorioMidiaSeguro, temporario: str, final: str, descritor: int) -> None:
            caminho = self.raiz / temporario
            caminho.unlink()
            caminho.symlink_to(externo)
            original(raiz, temporario, final, descritor)

        with patch.object(DiretorioMidiaSeguro, "publicar", trocar):
            with self.assertRaises(OSError):
                await self.midia._executar(self.midia._publicar, CHAVE, WEBP)
        self.assertFalse((self.raiz / CHAVE).exists())
        self.assertEqual(externo.read_bytes(), b"externo-intocavel")

    async def test_raiz_e_ancestral_links_sao_recusados_antes_dos_efeitos(self) -> None:
        self.trocar_raiz()
        with self.assertRaises(OSError):
            self.midia._abrir_diretorio()
        with self.assertRaises(OSError):
            await self.midia.remover(CHAVE)
        with self.assertRaises(OSError):
            await self.midia._executar(self.midia._publicar, CHAVE, WEBP)
        self.assertEqual(list(self.fora.iterdir()), [])


@unittest.skipUnless(os.name == "nt", "Handles de diretório Windows")
class TestCaminhosMidiaWindows(unittest.TestCase):
    def test_handle_impede_renomear_raiz_e_ancestral(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dealbot-handles-") as tmp:
            pai = Path(tmp) / "pai"
            raiz = pai / "midia"
            raiz.mkdir(parents=True)
            with DiretorioMidiaSeguro(raiz):
                for caminho in (raiz, pai):
                    with self.assertRaises(OSError):
                        caminho.rename(caminho.with_name(caminho.name + "-trocado"))
            raiz.rename(pai / "midia-liberada")


class TestCancelamentoFisico(unittest.IsolatedAsyncioTestCase):
    async def test_cancelamentos_repetidos_nao_liberam_slot_ou_submetem_fila(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dealbot-cancelamento-") as tmp:
            midia = ArmazenamentoLocal(Path(tmp), max_entrada=1000, max_pixels=100,
                                      lado_max=10, max_saida=1000)
            iniciou = asyncio.Event()
            liberar = threading.Event()
            loop = asyncio.get_running_loop()

            def trabalho() -> None:
                loop.call_soon_threadsafe(iniciou.set)
                if not liberar.wait(10):
                    raise RuntimeError("barreira_nao_liberada")

            primeiro = segundo = None
            try:
                with patch.object(midia._executor, "submit", wraps=midia._executor.submit) as submeter:
                    primeiro = asyncio.create_task(midia._executar(trabalho))
                    await asyncio.wait_for(iniciou.wait(), 5)
                    for _ in range(3):
                        primeiro.cancel()
                        await asyncio.sleep(0)
                    self.assertFalse(primeiro.done())
                    self.assertTrue(midia._vagas.locked())
                    segundo = asyncio.create_task(midia._executar(lambda: "concluido"))
                    await asyncio.sleep(0)
                    self.assertEqual(submeter.call_count, 1)
                    liberar.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await primeiro
                    self.assertEqual(await segundo, "concluido")
                    self.assertEqual(submeter.call_count, 2)
            finally:
                liberar.set()
                await asyncio.gather(*(t for t in (primeiro, segundo) if t), return_exceptions=True)
                await midia.fechar()
