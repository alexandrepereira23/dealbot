"""Destinos de mídia isolados; download continua pertencendo ao worker de mídia."""

import asyncio
import io
import math
import os
import re
import stat
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator, Protocol

from .modelos import ErroPermanente
from .midia_arquivos import DiretorioMidiaSeguro
from .politica import configurar_limites_http


BUCKET = "produtos"


class ArmazenamentoMidia(Protocol):
    async def enviar(self, chave: str, dados: bytes) -> str: ...

    async def remover(self, chave: str) -> None: ...

    async def url_publica(self, chave: str) -> str: ...


class ArmazenamentoSupabase:
    def __init__(self, client: Any, timeout: float = 30) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("O timeout de mídia deve ser positivo e finito")
        self._client = client
        self._timeout = timeout
        configurar_limites_http(getattr(getattr(client, "storage", None), "session", None))

    @staticmethod
    def _validar_chave(chave: str) -> None:
        if not isinstance(chave, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", chave):
            raise ValueError("A chave de mídia deve ser plana, segura e terminar em .jpg")

    async def enviar(self, chave: str, dados: bytes) -> str:
        self._validar_chave(chave)
        if not isinstance(dados, bytes):
            raise TypeError("O adaptador de mídia aceita somente bytes")
        bucket = self._client.storage.from_(BUCKET)
        # storage3 0.8 altera file_options ao converter upsert em x-upsert.
        opcoes = {"content-type": "image/jpeg", "upsert": "true"}
        resposta = await asyncio.wait_for(
            bucket.upload(chave, dados, opcoes), timeout=self._timeout
        )
        # A API desta versão retorna HTTPX Response, não dict de metadados.
        status = getattr(resposta, "status_code", None)
        if not isinstance(status, int) or not 200 <= status < 300:
            raise RuntimeError("Upload de mídia sem confirmação do Supabase")
        url = await asyncio.wait_for(bucket.get_public_url(chave), timeout=self._timeout)
        if not isinstance(url, str) or not url.strip():
            raise RuntimeError("URL pública ausente na resposta do Storage")
        return url

    async def remover(self, chave: str) -> None:
        self._validar_chave(chave)
        dados = await asyncio.wait_for(
            self._client.storage.from_(BUCKET).remove([chave]), timeout=self._timeout
        )
        # [] também confirma remoção idempotente de um objeto já ausente.
        if not isinstance(dados, list):
            raise RuntimeError("Remoção de mídia sem confirmação do Supabase")

    async def url_publica(self, chave: str) -> str:
        """Mesmo endereço usado no upload, inclusive para commit de upload ambíguo."""
        self._validar_chave(chave)
        url = await asyncio.wait_for(self._client.storage.from_(BUCKET).get_public_url(chave), self._timeout)
        if not isinstance(url, str) or not url:
            raise RuntimeError("url_publica_ausente")
        return url


CHAVE_LOCAL = re.compile(r"[a-f0-9]{32}\.webp\Z")
TEMP_PREFIXO = ".dealbot-media-"


class ArmazenamentoLocal:
    """Publica somente WebP final em diretório dedicado, sem substituir finais.

    A transformação acontece em executor próprio e limitado. Cancelar quem espera
    não libera o slot nem o lock físico até o trabalho de disco terminar.
    """

    def __init__(self, diretorio: Path, *, max_entrada: int, max_pixels: int,
                 lado_max: int, max_saida: int, workers: int = 1) -> None:
        if not diretorio.is_absolute():
            raise ValueError("O diretório local de mídia precisa ser absoluto")
        for nome, valor in (("max_entrada", max_entrada), ("max_pixels", max_pixels),
                            ("lado_max", lado_max), ("max_saida", max_saida), ("workers", workers)):
            if type(valor) is not int or valor <= 0:
                raise ValueError(f"{nome} precisa ser inteiro positivo")
        self.diretorio = diretorio
        self.max_entrada = max_entrada
        self.max_pixels = max_pixels
        self.lado_max = lado_max
        self.max_saida = max_saida
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="midia-local")
        self._vagas = asyncio.Semaphore(workers)
        self._fechado = False
        self._lock_limpeza = threading.Lock()
        self._raiz_limpeza: DiretorioMidiaSeguro | None = None
        self._entradas_limpeza: Iterator[str] | None = None

    @staticmethod
    def _validar_chave(chave: str) -> None:
        if not isinstance(chave, str) or CHAVE_LOCAL.fullmatch(chave) is None:
            raise ValueError("A chave local de mídia é inválida")

    def _caminho(self, chave: str) -> Path:
        self._validar_chave(chave)
        return self.diretorio / chave

    async def _executar(self, fn, *args):
        async with self._vagas:
            futuro = asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)
            cancelado = False
            while True:
                try:
                    resultado = await asyncio.shield(futuro)
                except asyncio.CancelledError:
                    # Também o segundo/terceiro cancelamento não pode cancelar o
                    # Future do executor nem liberar capacidade física cedo.
                    cancelado = True
                    if futuro.cancelled():
                        raise
                except Exception:
                    if cancelado:
                        raise asyncio.CancelledError from None
                    raise
                else:
                    if cancelado:
                        raise asyncio.CancelledError
                    return resultado

    def _abrir_diretorio(self) -> None:
        with DiretorioMidiaSeguro(self.diretorio, criar=True) as raiz:
            # Grupo confiável compartilha somente os finais com a API; setgid evita
            # perder o grupo herdado quando o volume já foi preparado na etapa 5.
            if raiz.fd is not None:
                os.fchmod(raiz.fd, 0o2770)

    def _preparar(self) -> None:
        self._abrir_diretorio()
        try:
            from PIL import features
        except ImportError as erro:
            raise RuntimeError("pillow_ausente") from erro
        if not features.check("webp"):
            raise RuntimeError("pillow_sem_webp")

    async def preparar(self) -> None:
        """Falha cedo antes da coleta se o destino local não estiver utilizável."""
        await self._executar(self._preparar)

    @staticmethod
    def _travar(arquivo) -> None:
        if os.name == "nt":
            import msvcrt
            arquivo.seek(0)
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _destravar(arquivo) -> None:
        if os.name == "nt":
            import msvcrt
            arquivo.seek(0)
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)

    def _final_regular(self, raiz: DiretorioMidiaSeguro, chave: str) -> bool:
        try:
            info = raiz.stat(chave)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > self.max_saida:
            raise OSError("arquivo_final_local_inseguro")
        descritor = raiz.abrir(chave, os.O_RDONLY)
        try:
            aberto = os.fstat(descritor)
            if not stat.S_ISREG(aberto.st_mode):
                raise OSError("arquivo_final_local_inseguro")
            with os.fdopen(os.dup(descritor), "rb") as arquivo:
                dados = arquivo.read(self.max_saida + 1)
            if len(dados) != aberto.st_size:
                raise OSError("arquivo_final_local_incompativel")
            try:
                from PIL import Image, UnidentifiedImageError
                with Image.open(io.BytesIO(dados), formats=("WEBP",)) as imagem:
                    if imagem.format != "WEBP" or getattr(imagem, "is_animated", False) or getattr(imagem, "n_frames", 1) != 1:
                        raise OSError("arquivo_final_local_incompativel")
                    largura, altura = imagem.size
                    if (largura <= 0 or altura <= 0 or largura * altura > self.max_pixels
                            or max(largura, altura) > self.lado_max):
                        raise OSError("arquivo_final_local_incompativel")
                    imagem.load()
            except (UnidentifiedImageError, OSError, ValueError) as erro:
                if isinstance(erro, OSError) and str(erro) == "arquivo_final_local_incompativel":
                    raise
                raise OSError("arquivo_final_local_incompativel") from erro
        finally:
            os.close(descritor)
        return True

    def _converter(self, dados: bytes) -> bytes:
        if not isinstance(dados, bytes):
            raise TypeError("A mídia local aceita somente bytes")
        if not dados or len(dados) > self.max_entrada:
            raise ErroPermanente("midia_excede_limite")
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError as erro:  # Defesa para instalação incompleta, nunca aceita sem validar.
            raise RuntimeError("pillow_ausente") from erro
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(dados), formats=("JPEG", "PNG", "WEBP")) as origem:
                    if getattr(origem, "is_animated", False) or getattr(origem, "n_frames", 1) != 1:
                        raise ErroPermanente("midia_animada")
                    largura, altura = origem.size
                    if largura <= 0 or altura <= 0 or largura * altura > self.max_pixels:
                        raise ErroPermanente("midia_pixels_excede_limite")
                    # load valida o stream antes de copiarmos pixels; exif_transpose
                    # aplica somente a orientação e a imagem nova não carrega EXIF/XMP.
                    origem.load()
                    normalizada = ImageOps.exif_transpose(origem).convert("RGB")
                    normalizada.thumbnail((self.lado_max, self.lado_max), Image.Resampling.LANCZOS)
                    for qualidade in (82, 78, 74, 70, 66, 62):
                        saida = io.BytesIO()
                        normalizada.save(saida, format="WEBP", quality=qualidade, method=4)
                        convertido = saida.getvalue()
                        if len(convertido) <= self.max_saida:
                            return convertido
        except ErroPermanente:
            raise
        except (UnidentifiedImageError, OSError, ValueError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as erro:
            raise ErroPermanente("midia_invalida") from erro
        raise ErroPermanente("midia_saida_excede_limite")

    def _publicar(self, chave: str, dados: bytes) -> None:
        with DiretorioMidiaSeguro(self.diretorio) as raiz:
            if self._final_regular(raiz, chave):
                return
            descritor, temporario = raiz.temporario(TEMP_PREFIXO)
            try:
                with os.fdopen(descritor, "w+b", closefd=True) as arquivo:
                    self._travar(arquivo)
                    arquivo.write(dados)
                    arquivo.flush()
                    os.fsync(arquivo.fileno())
                    if raiz.fd is not None:
                        os.fchmod(arquivo.fileno(), 0o640)
                    try:
                        raiz.publicar(temporario, chave, arquivo.fileno())
                    except FileExistsError:
                        self._final_regular(raiz, chave)
                    raiz.sincronizar()
            finally:
                try:
                    raiz.remover(temporario)
                except FileNotFoundError:
                    pass

    def _transformar_e_publicar(self, chave: str, dados: bytes) -> None:
        self._publicar(chave, self._converter(dados))

    async def enviar(self, chave: str, dados: bytes) -> str:
        self._validar_chave(chave)
        await self._executar(self._transformar_e_publicar, chave, dados)
        return await self.url_publica(chave)

    async def url_publica(self, chave: str) -> str:
        self._validar_chave(chave)
        return f"/media/{chave}"

    async def publicada(self, chave: str) -> bool:
        """Confere final conhecido antes de repetir download após checkpoint ambíguo."""
        self._validar_chave(chave)
        return await self._executar(self._publicada, chave)

    def _publicada(self, chave: str) -> bool:
        with DiretorioMidiaSeguro(self.diretorio) as raiz:
            return self._final_regular(raiz, chave)

    def _remover(self, chave: str) -> None:
        with DiretorioMidiaSeguro(self.diretorio) as raiz:
            try:
                info = raiz.stat(chave)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise OSError("arquivo_local_inseguro")
            raiz.remover(chave)
            raiz.sincronizar()

    async def remover(self, chave: str) -> None:
        self._validar_chave(chave)
        await self._executar(self._remover, chave)

    def _limpar_temporarios(self, agora: float, idade_minima: float, limite: int, exame: int) -> int:
        # O cursor e a âncora pertencem à instância, não ao await de um ciclo.
        # Serializar aqui (no executor) também cobre configurações com workers > 1.
        with self._lock_limpeza:
            try:
                if self._raiz_limpeza is None:
                    self._raiz_limpeza = DiretorioMidiaSeguro(self.diretorio)
                    self._entradas_limpeza = self._raiz_limpeza.listar()
                return self._limpar_na_raiz(self._raiz_limpeza, agora, idade_minima, limite, exame)
            except BaseException:
                self._fechar_limpeza()
                raise

    def _fechar_limpeza(self) -> None:
        entradas, raiz = self._entradas_limpeza, self._raiz_limpeza
        self._entradas_limpeza = self._raiz_limpeza = None
        try:
            fechar = getattr(entradas, "close", None)
            if fechar:
                fechar()
        finally:
            if raiz is not None:
                raiz.fechar()

    def _limpar_na_raiz(self, raiz: DiretorioMidiaSeguro, agora: float,
                       idade_minima: float, limite: int, exame: int) -> int:
        removidos = 0
        vistos = 0
        while vistos < exame and removidos < limite:
            try:
                nome = next(self._entradas_limpeza)
            except StopIteration:
                # Não reiniciar a varredura no mesmo ciclo. Uma nova âncora no
                # próximo ciclo também evita reutilizar o offset do fd POSIX.
                self._fechar_limpeza()
                break
            vistos += 1
            if not nome.startswith(TEMP_PREFIXO):
                continue
            try:
                info = raiz.stat(nome)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or agora - info.st_mtime < idade_minima:
                continue
            try:
                apagar_depois_de_fechar = False
                descritor = raiz.abrir(nome, os.O_RDWR)
                with os.fdopen(descritor, "r+b") as arquivo:
                    aberto = os.fstat(arquivo.fileno())
                    if not stat.S_ISREG(aberto.st_mode):
                        continue
                    self._travar(arquivo)
                    if os.name == "nt":
                        # Windows não permite unlink de arquivo aberto por este
                        # processo. A convenção exclusiva de temporário e o lock
                        # já provaram que não é escritor ativo; soltar/fechar e
                        # apagar em seguida é o equivalente local possível.
                        self._destravar(arquivo)
                        apagar_depois_de_fechar = True
                    else:
                        raiz.remover(nome)
                        removidos += 1
                if apagar_depois_de_fechar:
                    raiz.remover(nome)
                    removidos += 1
            except (BlockingIOError, PermissionError, FileNotFoundError, OSError):
                # Escrita ativa, ACL ou corrida: a próxima varredura tenta de novo.
                continue
        return removidos

    async def limpar_temporarios(self, agora: float | None = None, idade_minima: float = 86400,
                                 limite: int = 100, exame: int = 1000) -> int:
        if limite < 1 or exame < 1 or idade_minima <= 0:
            raise ValueError("limite_de_temporarios_invalido")
        return await self._executar(self._limpar_temporarios, time.time() if agora is None else agora,
                                    idade_minima, limite, exame)

    async def fechar(self) -> None:
        if not self._fechado:
            self._executor.shutdown(wait=True)
            with self._lock_limpeza:
                self._fechar_limpeza()
            self._fechado = True


class ArmazenamentosMidia:
    """Seleciona o destino congelado no job; modo atual nunca redireciona retry."""

    def __init__(self, supabase: ArmazenamentoMidia, local: ArmazenamentoMidia | None = None) -> None:
        self.supabase = supabase
        self.local = local

    def para(self, destino: str) -> ArmazenamentoMidia:
        if destino == "supabase":
            return self.supabase
        if destino == "local" and self.local is not None:
            return self.local
        raise RuntimeError("destino_de_midia_indisponivel")

    async def limpar_temporarios(self) -> int:
        limpar = getattr(self.local, "limpar_temporarios", None)
        return await limpar() if limpar else 0

    async def preparar(self) -> None:
        preparar = getattr(self.local, "preparar", None)
        if preparar:
            await preparar()

    async def fechar(self) -> None:
        fechar = getattr(self.local, "fechar", None)
        if fechar:
            await fechar()
