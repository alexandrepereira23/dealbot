"""CA-004/005/006/008: codecs reais, ext4/locks e SQLite temporário.

Sem serviços externos. ENOSPC/EACCES são syscalls SINTÉTICAS injetadas no
fsync do arquivo de mídia, não disco cheio/ACL reais nem falhas do SQLite.
"""

import asyncio
import errno
import importlib.util
import io
import os
import stat
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cenarios_identidade import (
    RepositorioIdentidadeFake, ResolvedorFake, TelegramFake, aguardar,
    linhas, mensagem_sintetica,
)
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.midia import ArmazenamentoLocal, ArmazenamentosMidia, TEMP_PREFIXO
from src.modelos import ErroPermanente
from src.pipeline_identidade import PipelineIdentidade


TEM_PILLOW = importlib.util.find_spec("PIL") is not None
CHAVE = "0123456789abcdef0123456789abcdef.webp"
OUTRA_CHAVE = "fedcba9876543210fedcba9876543210.webp"
MAX_ENTRADA = 10_485_760
MAX_PIXELS = 24_000_000
MAX_SAIDA = 358_400


def imagem(formato="PNG", tamanho=(40, 20), *, metadados=False, orientacao=None):
    from PIL import Image, PngImagePlugin

    with Image.new("RGB", tamanho, (23, 81, 143)) as origem:
        opcoes = {}
        if metadados or orientacao is not None:
            exif = Image.Exif()
            exif[274] = orientacao or 1
            exif[270] = "descricao-privada-sintetica"
            exif[34853] = {1: "N", 2: (1.0, 2.0, 3.0)}
            opcoes["exif"] = exif.tobytes()
        if metadados:
            opcoes["icc_profile"] = b"perfil-privado-sintetico"
            if formato in {"JPEG", "WEBP"}:
                opcoes["xmp"] = b"<x:xmpmeta>privado-sintetico</x:xmpmeta>"
            if formato == "JPEG":
                opcoes["comment"] = b"comentario-privado-sintetico"
            if formato == "PNG":
                info = PngImagePlugin.PngInfo()
                info.add_text("Comment", "comentario-privado-sintetico")
                info.add_itxt("XML:com.adobe.xmp", "xmp-privado-sintetico")
                opcoes["pnginfo"] = info
        saida = io.BytesIO()
        origem.save(saida, format=formato, **opcoes)
        return saida.getvalue()


class StorageProibido:
    def __getattr__(self, nome):
        raise AssertionError(f"storage_proibido_{nome}")


@unittest.skipUnless(TEM_PILLOW, "Pillow fixado em requirements.txt é necessário")
class TestImagensELimites(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="midia-limites-")
        self.raiz = Path(self.tmp.name) / "midia"
        self.midia = self.adaptador()
        await self.midia.preparar()

    def adaptador(self, **opcoes):
        limites = dict(max_entrada=MAX_ENTRADA, max_pixels=MAX_PIXELS,
                       lado_max=960, max_saida=MAX_SAIDA)
        limites.update(opcoes)
        return ArmazenamentoLocal(self.raiz, **limites)

    async def asyncTearDown(self):
        await self.midia.fechar()
        self.tmp.cleanup()

    def conferir_final(self, chave, tamanho):
        from PIL import Image

        dados = (self.raiz / chave).read_bytes()
        self.assertLessEqual(len(dados), MAX_SAIDA)
        with Image.open(io.BytesIO(dados)) as final:
            final.load()
            self.assertEqual(final.format, "WEBP")
            self.assertEqual(final.size, tamanho)
            self.assertEqual(getattr(final, "n_frames", 1), 1)
            self.assertFalse(getattr(final, "is_animated", False))
            self.assertEqual(dict(final.getexif()), {})
            for campo in ("exif", "xmp", "icc_profile", "comment", "Comment", "XML:com.adobe.xmp"):
                self.assertFalse(final.info.get(campo), campo)
        for privado in (b"privado", b"privada", b"sintetico"):
            self.assertNotIn(privado, dados)

    async def test_matriz_jpeg_png_webp_estaticos_formas_pequenas_e_grandes(self):
        for indice, formato in enumerate(("JPEG", "PNG", "WEBP")):
            for numero, (entrada, esperado) in enumerate((
                ((1600, 900), (960, 540)), ((900, 1600), (540, 960)),
                ((1200, 1200), (960, 960)), ((40, 20), (40, 20)),
                ((20, 40), (20, 40)), ((20, 20), (20, 20)),
            )):
                with self.subTest(formato=formato, entrada=entrada):
                    chave = f"{indice * 10 + numero:032x}.webp"
                    dados = imagem(formato, entrada, metadados=True)
                    from PIL import Image
                    with Image.open(io.BytesIO(dados)) as original:
                        self.assertTrue(original.getexif())
                        self.assertTrue(original.info.get("icc_profile"))
                    self.assertEqual(await self.midia.enviar(chave, dados), f"/media/{chave}")
                    self.conferir_final(chave, esperado)

    async def test_orientacao_visual_de_todos_os_formatos_sem_exif_no_final(self):
        for indice, formato in enumerate(("JPEG", "PNG", "WEBP")):
            with self.subTest(formato=formato):
                chave = f"{100 + indice:032x}.webp"
                await self.midia.enviar(chave, imagem(formato, (1600, 900),
                    metadados=True, orientacao=6))
                self.conferir_final(chave, (540, 960))

    async def test_bytes_dez_mib_inclusivo_e_mais_um_antes_do_decoder(self):
        dados = imagem()
        dados += b"\0" * (MAX_ENTRADA - len(dados))
        self.assertEqual(len(dados), MAX_ENTRADA)
        await self.midia.enviar(CHAVE, dados)
        self.conferir_final(CHAVE, (40, 20))
        with patch("PIL.Image.open", side_effect=AssertionError("nao_deve_decodificar")):
            with self.assertRaisesRegex(ErroPermanente, "midia_excede_limite"):
                await self.midia.enviar(OUTRA_CHAVE, dados + b"\0")
        self.assertFalse((self.raiz / OUTRA_CHAVE).exists())

    async def test_pixels_vinte_quatro_milhoes_inclusivo_e_mais_um(self):
        await self.midia.enviar(CHAVE, imagem(tamanho=(6000, 4000)))
        self.conferir_final(CHAVE, (960, 640))
        # PNG real de 24.000.001 pixels; o limite deve agir ANTES de load/resize.
        dados = imagem(tamanho=(24_000_001, 1))
        with patch("PIL.Image.Image.load", side_effect=AssertionError("decode_tardio")):
            with self.assertRaisesRegex(ErroPermanente, "midia_pixels_excede_limite"):
                await self.midia.enviar(OUTRA_CHAVE, dados)
        self.assertFalse((self.raiz / OUTRA_CHAVE).exists())

    async def test_saida_real_limite_inclusivo_e_um_byte_acima_seis_tentativas(self):
        from PIL import Image

        dados = imagem(tamanho=(320, 180))
        tamanhos = []
        with Image.open(io.BytesIO(dados)) as origem:
            for qualidade in (82, 78, 74, 70, 66, 62):
                saida = io.BytesIO()
                origem.save(saida, format="WEBP", quality=qualidade, method=4)
                tamanhos.append(len(saida.getvalue()))
        minimo = min(tamanhos)
        inclusivo = self.adaptador(max_saida=minimo)
        impossivel = self.adaptador(max_saida=minimo - 1)
        salvar = Image.Image.save
        tentativas = []

        def contar(origem, *args, **opcoes):
            tentativas.append(opcoes["quality"])
            return salvar(origem, *args, **opcoes)

        try:
            await inclusivo.enviar(CHAVE, dados)
            self.assertEqual((self.raiz / CHAVE).stat().st_size, minimo)
            with patch.object(Image.Image, "save", new=contar):
                with self.assertRaisesRegex(ErroPermanente, "midia_saida_excede_limite"):
                    await impossivel.enviar(OUTRA_CHAVE, dados)
            self.assertEqual(tentativas, [82, 78, 74, 70, 66, 62])
            self.assertFalse((self.raiz / OUTRA_CHAVE).exists())
        finally:
            await inclusivo.fechar()
            await impossivel.fechar()

    async def test_final_limite_padrao_350_kib_inclusivo_e_mais_um(self):
        await self.midia.enviar(CHAVE, imagem())
        dados = (self.raiz / CHAVE).read_bytes()
        # Padding após RIFF: WebP ainda decodificável, teste de tamanho físico real.
        (self.raiz / CHAVE).write_bytes(dados + b"\0" * (MAX_SAIDA - len(dados)))
        self.assertTrue(await self.midia.publicada(CHAVE))
        (self.raiz / OUTRA_CHAVE).write_bytes((self.raiz / CHAVE).read_bytes() + b"\0")
        with self.assertRaisesRegex(OSError, "arquivo_final_local_inseguro"):
            await self.midia.publicada(OUTRA_CHAVE)

    async def test_tipos_disfarcados_nao_aceitos_e_truncados_sem_final(self):
        from PIL import Image

        negativos = [("svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
                     ("pdf", b"%PDF-1.7\n"), ("executavel", b"MZ\0\0\0\0"),
                     ("vazio", b""), ("texto_jpg", b"nao e JPEG")]
        for formato in ("GIF", "BMP", "TIFF"):
            saida = io.BytesIO()
            with Image.new("RGB", (20, 20)) as origem:
                origem.save(saida, format=formato)
            negativos.append((formato, saida.getvalue()))
        for formato in ("JPEG", "PNG", "WEBP"):
            valido = imagem(formato, (160, 90))
            negativos.append((f"{formato}_truncado", valido[:len(valido) // 2]))
        for nome, dados in negativos:
            with self.subTest(nome=nome):
                with self.assertRaises(ErroPermanente):
                    await self.midia.enviar(CHAVE, dados)
                self.assertEqual(list(self.raiz.iterdir()), [])

    async def test_apng_e_webp_animados_recusados(self):
        from PIL import Image

        with Image.new("RGB", (20, 20), "red") as primeiro, \
             Image.new("RGB", (20, 20), "blue") as segundo:
            for formato in ("PNG", "WEBP"):
                with self.subTest(formato=formato):
                    saida = io.BytesIO()
                    primeiro.save(saida, format=formato, save_all=True,
                        append_images=[segundo], duration=100, loop=0)
                    with self.assertRaisesRegex(ErroPermanente, "midia_animada"):
                        await self.midia.enviar(CHAVE, saida.getvalue())
                    self.assertEqual(list(self.raiz.iterdir()), [])

    async def test_bomba_warning_e_falha_permanente_nao_retry(self):
        from PIL import Image

        # Dispara a proteção REAL do Pillow sem alocar uma bomba. Limite de
        # segurança somente reduzido neste teste; nunca desabilitado em produção.
        dados = imagem(tamanho=(11, 10))
        with patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(ErroPermanente, "midia_invalida"):
                await self.midia.enviar(CHAVE, dados)
        self.assertEqual(list(self.raiz.iterdir()), [])

    async def test_bomba_error_e_falha_permanente(self):
        from PIL import Image

        dados = imagem(tamanho=(21, 10))
        with patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(ErroPermanente, "midia_invalida"):
                await self.midia.enviar(CHAVE, dados)
        self.assertEqual(list(self.raiz.iterdir()), [])


@unittest.skipUnless(TEM_PILLOW, "Pillow fixado em requirements.txt é necessário")
@unittest.skipIf(os.name == "nt", "Locks/permissões reais exigem POSIX")
class TestCancelamentoETemporarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="midia-cancelamento-")
        self.raiz = Path(self.tmp.name) / "midia"
        self.midia = ArmazenamentoLocal(self.raiz, max_entrada=MAX_ENTRADA,
            max_pixels=MAX_PIXELS, lado_max=960, max_saida=MAX_SAIDA, workers=1)
        self.limpador = ArmazenamentoLocal(self.raiz, max_entrada=MAX_ENTRADA,
            max_pixels=MAX_PIXELS, lado_max=960, max_saida=MAX_SAIDA, workers=1)
        await self.midia.preparar()

    async def asyncTearDown(self):
        await self.midia.fechar()
        await self.limpador.fechar()
        self.tmp.cleanup()

    async def test_cancelamentos_repetidos_mantem_slot_e_lock_ate_fsync_acabar(self):
        loop = asyncio.get_running_loop()
        iniciou = asyncio.Event()
        liberar = threading.Event()
        sincronizar = os.fsync
        atingiu = False
        chamadas = []

        def fsync_lento(fd):
            nonlocal atingiu
            if stat.S_ISREG(os.fstat(fd).st_mode) and not atingiu:
                atingiu = True
                loop.call_soon_threadsafe(iniciou.set)
                if not liberar.wait(10):
                    raise AssertionError("watchdog_fsync_sintetico")
            return sincronizar(fd)

        publicar = self.midia._transformar_e_publicar

        def contar(chave, dados):
            chamadas.append(chave)
            return publicar(chave, dados)

        tarefas = []
        with patch("src.midia.os.fsync", side_effect=fsync_lento), \
             patch.object(self.midia, "_transformar_e_publicar", side_effect=contar), \
             patch.object(self.midia._executor, "submit", wraps=self.midia._executor.submit) as submeter:
            try:
                tarefas.append(asyncio.create_task(self.midia.enviar(CHAVE, imagem())))
                await asyncio.wait_for(iniciou.wait(), 3)
                temporarios = list(self.raiz.glob(f"{TEMP_PREFIXO}*"))
                self.assertEqual(len(temporarios), 1)
                antigo = time.time() - 90_000
                os.utime(temporarios[0], (antigo, antigo))
                for _ in range(3):
                    tarefas[0].cancel()
                    await asyncio.sleep(0)
                tarefas.append(asyncio.create_task(self.midia.enviar(OUTRA_CHAVE, imagem())))
                await asyncio.sleep(0)
                self.assertFalse(tarefas[0].done(), "cancelamento não termina trabalho físico")
                self.assertFalse(tarefas[1].done())
                self.assertEqual(chamadas, [CHAVE], "segundo trabalho não entra no executor")
                self.assertEqual(submeter.call_count, 1, "não acumula trabalho na fila do executor")
                self.assertEqual(await self.limpador.limpar_temporarios(), 0)
                self.assertTrue(temporarios[0].exists(), "lock físico protege mesmo com idade antiga")
                self.assertFalse((self.raiz / CHAVE).exists(), "nenhum final parcial")
                liberar.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(tarefas[0], 3)
                await asyncio.wait_for(tarefas[1], 3)
                self.assertEqual(submeter.call_count, 2)
                self.assertTrue(await self.midia.publicada(CHAVE))
                self.assertTrue(await self.midia.publicada(OUTRA_CHAVE))
                finais = {p.name: p.read_bytes() for p in self.raiz.glob("*.webp")}
                self.assertEqual(await self.limpador.limpar_temporarios(), 0)
                self.assertEqual({p.name: p.read_bytes() for p in self.raiz.glob("*.webp")}, finais)
            finally:
                liberar.set()
                await asyncio.gather(*tarefas, return_exceptions=True)

    async def test_reinicio_limpa_so_abandonados_com_orcamento_e_sem_seguir_link(self):
        await self.midia.enviar(CHAVE, imagem())
        final = (self.raiz / CHAVE).read_bytes()
        antigo = time.time() - 90_000
        os.utime(self.raiz / CHAVE, (antigo, antigo))
        externo = Path(self.tmp.name) / "arquivo-do-usuario"
        externo.write_bytes(b"preservar")
        outros = self.raiz / "temporario-do-usuario.tmp"
        outros.write_bytes(b"preservar")
        link = self.raiz / f"{TEMP_PREFIXO}link.tmp"
        link.symlink_to(externo)
        novo = self.raiz / f"{TEMP_PREFIXO}recente.tmp"
        novo.write_bytes(b"recente")
        abandonados = []
        for numero in range(3):
            caminho = self.raiz / f"{TEMP_PREFIXO}{numero:032x}.tmp"
            caminho.write_bytes(b"abandonado")
            os.utime(caminho, (antigo, antigo))
            abandonados.append(caminho)
        await self.midia.fechar()
        # Outro adaptador = nenhuma flag em memória do escritor anterior.
        self.assertEqual(await self.limpador.limpar_temporarios(limite=1, exame=1000), 1)
        self.assertEqual(sum(p.exists() for p in abandonados), 2)
        inspecao_curta = await self.limpador.limpar_temporarios(limite=100, exame=1)
        # Não presume ordem de scandir: um nome permite no máximo uma exclusão.
        self.assertLessEqual(inspecao_curta, 1)
        self.assertEqual(sum(p.exists() for p in abandonados), 2 - inspecao_curta)
        self.assertEqual(await self.limpador.limpar_temporarios(limite=100, exame=1000),
                         2 - inspecao_curta)
        self.assertEqual((self.raiz / CHAVE).read_bytes(), final)
        self.assertEqual(externo.read_bytes(), b"preservar")
        self.assertEqual(outros.read_bytes(), b"preservar")
        self.assertTrue(link.is_symlink())
        self.assertTrue(novo.exists())


@unittest.skipUnless(TEM_PILLOW, "Pillow fixado em requirements.txt é necessário")
class TestFalhasNoPipelineAtivo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="midia-pipeline-limites-")
        raiz = Path(self.tmp.name)
        self.config = replace(Config(), state_dir=raiz / "estado", midia_modo="local",
            midia_local_dir=raiz / "midia", retry_base=30, retry_max=30)
        self.estado = EstadoLocal(self.config.state_dir)
        await self.estado.abrir()
        self.local = ArmazenamentoLocal(self.config.midia_local_dir, max_entrada=MAX_ENTRADA,
            max_pixels=MAX_PIXELS, lado_max=960, max_saida=MAX_SAIDA)
        await self.local.preparar()
        self.repo = RepositorioIdentidadeFake()
        self.telegram = TelegramFake()
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.pipeline = PipelineIdentidade(self.estado, self.repo,
            ArmazenamentosMidia(StorageProibido(), self.local), self.telegram,
            self.cache, self.config, resolvedor=ResolvedorFake())

    async def asyncTearDown(self):
        await self.pipeline.encerrar()
        await self.local.fechar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def agendar(self):
        mensagem = mensagem_sintetica(foto=True)
        await self.estado.registrar(mensagem)
        await self.pipeline._oferta(await self.estado.obter_oferta(time.time(), True))
        evento = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
        self.assertIsNotNone(evento["disponibilizado_em"])
        self.produto_id = evento["produto_id"]
        return await self.estado.midia(self.produto_id)

    async def conferir_oferta_e_durabilidade(self, job):
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertTrue(self.repo.cards[self.produto_id]["link"])
        self.assertIsNone(self.repo.cards[self.produto_id]["foto_url"])
        self.assertEqual(self.repo.chamadas["vincular_foto"], 0)
        self.assertEqual(self.repo.reservas, set())
        atual = await self.estado.midia(self.produto_id)
        self.assertEqual(atual["enviado"], 0)
        self.assertEqual((atual["chave"], atual["destino"]), (job["chave"], "local"))
        self.assertIsNone(atual["url"])
        self.assertEqual(list(self.local.diretorio.iterdir()), [])
        self.assertEqual((await linhas(self.estado, "PRAGMA journal_mode"))[0]["journal_mode"], "wal")
        self.assertEqual((await linhas(self.estado, "PRAGMA synchronous"))[0]["synchronous"], 2)
        return atual

    async def falha_syscall(self, codigo):
        job = await self.agendar()
        sincronizar = os.fsync

        def falhar(fd):
            # Injeção estritamente no inode regular do volume de MÍDIA: SQLite
            # mantém seu executor/conexão WAL/FULL e não passa por esta syscall.
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(codigo, "syscall_midia_sintetica")
            return sincronizar(fd)

        with patch.object(self.telegram, "baixar_foto", return_value=imagem()), \
             patch("src.midia.os.fsync", side_effect=falhar):
            self.pipeline.iniciar()

            async def retry_gravado():
                atual = await self.estado.midia(self.produto_id)
                return atual["estado"] == "retry" and atual["erro"] is not None

            await aguardar(retry_gravado, pipeline=self.pipeline)
            await self.pipeline.encerrar()
        atual = await self.conferir_oferta_e_durabilidade(job)
        self.assertEqual(atual["estado"], "retry")
        self.assertIsNone(atual["finalizado_em"])
        self.assertGreater(atual["proxima"], time.time())
        self.assertEqual(atual["tentativas"], 1)
        self.assertIsNotNone(atual["erro"])
        await self.estado.fechar()
        self.estado = EstadoLocal(self.config.state_dir)
        await self.estado.abrir()
        self.pipeline.estado = self.estado
        retomada = await self.estado.midia(self.produto_id)
        self.assertEqual(retomada["estado"], "retry")
        self.assertEqual(retomada["chave"], job["chave"])
        self.assertEqual(retomada["proxima"], atual["proxima"])

    async def test_enospc_sintetico_preserva_oferta_pending_e_recuo(self):
        await self.falha_syscall(errno.ENOSPC)

    async def test_eacces_sintetico_preserva_oferta_pending_e_recuo(self):
        await self.falha_syscall(errno.EACCES)

    @unittest.skipIf(os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
                     "Permissão POSIX real exige usuário não root")
    async def test_permissao_posix_real_no_volume_midia_preserva_sqlite(self):
        job = await self.agendar()
        # Diferentemente das duas injeções acima, o kernel nega a criação do
        # temporário num diretório sintético sem escrita; não é ACL Windows.
        os.chmod(self.local.diretorio, 0o550)
        try:
            with patch.object(self.telegram, "baixar_foto", return_value=imagem()):
                self.pipeline.iniciar()

                async def negada():
                    atual = await self.estado.midia(self.produto_id)
                    return atual["estado"] == "retry" and atual["erro"] == "PermissionError"

                await aguardar(negada, pipeline=self.pipeline)
                await self.pipeline.encerrar()
            atual = await self.conferir_oferta_e_durabilidade(job)
            self.assertIsNone(atual["finalizado_em"])
            self.assertGreater(atual["proxima"], time.time())
        finally:
            os.chmod(self.local.diretorio, 0o2770)

    async def test_invalida_terminaliza_midia_sem_apagar_oferta(self):
        job = await self.agendar()
        with patch.object(self.telegram, "baixar_foto", return_value=b"%PDF-1.7\n"):
            self.pipeline.iniciar()

            async def falha_classificada():
                return bool((await self.estado.midia(self.produto_id))["falha_apos_limpeza"])

            await aguardar(falha_classificada, pipeline=self.pipeline)
            await self.pipeline.encerrar()
        pendente = await self.estado.midia(self.produto_id)
        self.assertEqual(pendente["estado"], "retry")
        self.assertGreater(pendente["proxima"], time.time())
        # Reconciliação exige outro claim. Avança explicitamente o relógio da
        # consulta SQLite, sem dormir, mudar o recuo ou ampliar o watchdog.
        retomada = await self.estado.obter_midia(pendente["proxima"])
        self.assertIsNotNone(retomada)
        await self.pipeline._midia(retomada)
        atual = await self.conferir_oferta_e_durabilidade(job)
        self.assertEqual(atual["estado"], "falha_permanente")
        self.assertIsNotNone(atual["finalizado_em"])
        self.assertIn("midia_invalida", atual["erro"])

    async def test_worker_lento_nao_bloqueia_coleta_novas_ofertas_ou_sqlite(self):
        await self.agendar()
        loop = asyncio.get_running_loop()
        iniciou = asyncio.Event()
        liberar = threading.Event()
        converter = self.local._converter

        def lento(dados):
            loop.call_soon_threadsafe(iniciou.set)
            if not liberar.wait(10):
                raise AssertionError("watchdog_conversao_sintetica")
            return converter(dados)

        with patch.object(self.telegram, "baixar_foto", return_value=imagem()), \
             patch.object(self.local, "_converter", side_effect=lento):
            self.pipeline.iniciar()
            try:
                await asyncio.wait_for(iniciou.wait(), 3)
                self.assertIsNone(self.repo.cards[self.produto_id]["foto_url"])
                await asyncio.wait_for(self.pipeline.receber(mensagem_sintetica(
                    msg_id=2, canal=-100222, contexto={}, url="https://loja.invalid/item/2")), 3)

                async def nova_disponivel():
                    evento = await self.estado.evento(-100222, 2)
                    return evento and evento["disponibilizado_em"] is not None

                await aguardar(nova_disponivel, timeout=3, pipeline=self.pipeline)
                self.assertFalse(liberar.is_set())
                self.assertEqual(len(self.repo.ativos), 2)
                self.assertLessEqual(self.pipeline.max_ativos["midia"], 1)
                liberar.set()

                async def pronta():
                    return (await self.estado.midia(self.produto_id))["estado"] == "pronta"

                await aguardar(pronta, pipeline=self.pipeline)
            finally:
                liberar.set()
                await self.pipeline.encerrar()
