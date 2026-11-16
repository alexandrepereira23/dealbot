"""Mídia local com imagens reais e disco temporário; sem Telegram/Supabase."""

import asyncio
import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Config
from src.estado import EstadoLocal
from src.midia import ArmazenamentoLocal, ArmazenamentosMidia
from src.modelos import ErroPermanente, Mensagem

TEM_PILLOW = importlib.util.find_spec("PIL") is not None
CHAVE = "0123456789abcdef0123456789abcdef.webp"
WEBP_MINIMO = b"RIFF\x04\x00\x00\x00WEBP"


@unittest.skipUnless(TEM_PILLOW, "Pillow fixado em requirements.txt é necessário")
class TestArmazenamentoLocal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self.tmp.name) / "midia"
        self.midia = ArmazenamentoLocal(self.diretorio, max_entrada=10 * 1024 * 1024,
            max_pixels=24_000_000, lado_max=960, max_saida=358400)
        await self.midia.preparar()

    async def asyncTearDown(self) -> None:
        await self.midia.fechar()
        self.tmp.cleanup()

    @staticmethod
    def imagem(formato: str, tamanho: tuple[int, int] = (1600, 900), *, orientacao: int | None = None) -> bytes:
        from PIL import Image
        import io

        imagem = Image.new("RGB", tamanho, color=(10, 80, 160))
        saida = io.BytesIO()
        opcoes = {}
        if orientacao is not None:
            exif = Image.Exif()
            exif[274] = orientacao
            exif[34853] = {1: "gps-nao-pode-vazar"}
            opcoes["exif"] = exif.tobytes()
        imagem.save(saida, format=formato, **opcoes)
        return saida.getvalue()

    async def test_converte_orienta_limita_e_nao_regrava_final(self) -> None:
        from PIL import Image
        import io

        entrada = self.imagem("JPEG", (1600, 900), orientacao=6)
        self.assertEqual(await self.midia.enviar(CHAVE, entrada), f"/media/{CHAVE}")
        caminho = self.diretorio / CHAVE
        primeiro = caminho.read_bytes()
        self.assertLessEqual(len(primeiro), 358400)
        with Image.open(io.BytesIO(primeiro)) as final:
            self.assertEqual(final.format, "WEBP")
            self.assertLessEqual(max(final.size), 960)
            self.assertEqual(final.size, (540, 960))
            self.assertEqual(dict(final.getexif()), {})
        await self.midia.enviar(CHAVE, self.imagem("PNG", (20, 20)))
        self.assertEqual(caminho.read_bytes(), primeiro, "retry não pode clobber final válido")
        self.assertTrue(await self.midia.publicada(CHAVE))

    async def test_pequena_nao_amplia_e_entrada_invalida_nao_publica(self) -> None:
        from PIL import Image
        import io

        chave_pequena = "fedcba9876543210fedcba9876543210.webp"
        await self.midia.enviar(chave_pequena, self.imagem("PNG", (40, 20)))
        with Image.open(io.BytesIO((self.diretorio / chave_pequena).read_bytes())) as final:
            self.assertEqual(final.size, (40, 20))
        with self.assertRaises(ErroPermanente):
            await self.midia.enviar(CHAVE, b"nao-e-imagem")
        self.assertFalse((self.diretorio / CHAVE).exists())

    async def test_final_truncado_com_magic_webp_e_erro_explicito(self) -> None:
        (self.diretorio / CHAVE).write_bytes(b"RIFF\x04\x00\x00\x00WEBP")
        with self.assertRaisesRegex(OSError, "arquivo_final_local_incompativel"):
            await self.midia.publicada(CHAVE)

    async def test_limites_e_temporarios_sao_finitos(self) -> None:
        limitado = ArmazenamentoLocal(self.diretorio, max_entrada=128, max_pixels=100,
            lado_max=20, max_saida=10000)
        try:
            with self.assertRaisesRegex(ErroPermanente, "midia_excede_limite"):
                await limitado.enviar(CHAVE, b"x" * 129)
            with self.assertRaisesRegex(ErroPermanente, "pixels"):
                await limitado.enviar(CHAVE, self.imagem("PNG", (11, 10)))
        finally:
            await limitado.fechar()
        abandonado = self.diretorio / ".dealbot-media-abandonado.tmp"
        abandonado.write_bytes(b"incompleto")
        antigo = time.time() - 90000
        os.utime(abandonado, (antigo, antigo))
        self.assertEqual(await self.midia.limpar_temporarios(agora=time.time(), limite=1, exame=10), 1)
        self.assertFalse(abandonado.exists())

    @unittest.skipIf(os.name == "nt", "Symlink POSIX é validado no ambiente alvo")
    async def test_link_final_e_rejeitado_sem_seguir(self) -> None:
        externo = Path(self.tmp.name) / "fora.webp"
        externo.write_bytes(b"RIFF0000WEBPfora")
        (self.diretorio / CHAVE).symlink_to(externo)
        with self.assertRaises(OSError):
            await self.midia.enviar(CHAVE, self.imagem("PNG", (20, 20)))
        self.assertEqual(externo.read_bytes(), b"RIFF0000WEBPfora")


class TestDestinoDuravel(unittest.IsolatedAsyncioTestCase):
    async def test_legado_fica_supabase_e_novo_local_tem_chave_opaca(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            estado = EstadoLocal(Path(temporario))
            await estado.abrir()
            try:
                msg = Mensagem(-1007, 4, "canal", "texto", "2026-01-01T00:00:00+00:00", True)
                await estado.registrar(msg)
                job = await estado.obter_oferta(time.time(), True)
                with patch("src.estado.secrets.token_hex", return_value="a" * 32):
                    await estado.finalizar_oferta(job, "aprovada", 99, midia=True, destino_midia="local")
                midia = await estado.midia(99)
                self.assertEqual((midia["destino"], midia["chave"]), ("local", "a" * 32 + ".webp"))
            finally:
                await estado.fechar()
        with self.assertRaises(ValueError):
            Config(midia_modo="local")

    async def test_diretorio_local_nunca_sobrepoe_estado_ou_codigo(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            estado = raiz / "estado"
            for destino in (estado, estado / "media", raiz):
                with self.assertRaisesRegex(ValueError, "dedicado"):
                    Config(state_dir=estado, midia_modo="local", midia_local_dir=destino)

    async def test_seletor_nao_faz_fallback_silencioso(self) -> None:
        class Supabase:
            pass
        destinos = ArmazenamentosMidia(Supabase())
        self.assertIsInstance(destinos.para("supabase"), Supabase)
        with self.assertRaisesRegex(RuntimeError, "destino_de_midia_indisponivel"):
            destinos.para("local")


@unittest.skipIf(os.name == "nt", "Links POSIX são requisito do ambiente alvo")
class TestFilesystemLocalPosix(unittest.IsolatedAsyncioTestCase):
    async def test_final_link_nunca_e_lido_substituido_ou_removido(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario) / "midia"
            externo = Path(temporario) / "segredo.webp"
            externo.write_bytes(WEBP_MINIMO)
            midia = ArmazenamentoLocal(raiz, max_entrada=100, max_pixels=100,
                lado_max=10, max_saida=100, workers=1)
            try:
                midia._abrir_diretorio()
                (raiz / CHAVE).symlink_to(externo)
                with self.assertRaises(OSError):
                    await midia.publicada(CHAVE)
                with self.assertRaises(OSError):
                    await midia.remover(CHAVE)
                self.assertEqual(externo.read_bytes(), WEBP_MINIMO)
            finally:
                await midia.fechar()
