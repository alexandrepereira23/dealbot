"""Operações planas ancoradas na raiz privada do volume de mídia."""

import os
import secrets
from pathlib import Path
from types import TracebackType
from typing import Iterator


def _handle_windows(caminho: Path, *, diretorio: bool) -> int:
    """Abre o próprio objeto e impede renomeá-lo enquanto o handle existir."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    criar = kernel.CreateFileW
    criar.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    criar.restype = wintypes.HANDLE
    fechar = kernel.CloseHandle
    fechar.argtypes = (wintypes.HANDLE,)
    fechar.restype = wintypes.BOOL
    atributos = kernel.GetFileInformationByHandleEx
    atributos.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    atributos.restype = wintypes.BOOL

    class Atributos(ctypes.Structure):
        _fields_ = [("atributos", wintypes.DWORD), ("tag", wintypes.DWORD)]

    # Sem FILE_SHARE_DELETE: nem o componente nem um ancestral podem ser trocados
    # após a abertura. OPEN_REPARSE_POINT examina o link/junction, não seu alvo.
    # GENERIC_READ é necessário também no diretório: um handle restrito a
    # FILE_READ_ATTRIBUTES não participa das mesmas regras de compartilhamento.
    handle = criar(str(caminho), 0x80000000, 0x1 | 0x2,
                   None, 3, 0x00200000 | (0x02000000 if diretorio else 0), None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = Atributos()
        if not atributos(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.atributos & 0x400 or bool(info.atributos & 0x10) != diretorio:
            raise OSError("objeto_local_de_midia_inseguro")
        return handle
    except BaseException:
        fechar(handle)
        raise


class DiretorioMidiaSeguro:
    """Prende cada componente da raiz antes de qualquer operação em filhos.

    POSIX usa openat/O_NOFOLLOW em todos os componentes e dir_fd nos filhos.
    Windows mantém handles sem compartilhamento de delete em todos os ancestrais
    e abre arquivos sem seguir reparse points. Não existe fallback por stat/path.
    """

    def __init__(self, caminho: Path, *, criar: bool = False) -> None:
        if not caminho.is_absolute() or ".." in caminho.parts:
            raise ValueError("diretorio_local_de_midia_invalido")
        self.caminho = caminho
        self.fd: int | None = None
        self._handles: list[int] = []
        try:
            if os.name == "nt":
                atual = Path(caminho.anchor)
                self._handles.append(_handle_windows(atual, diretorio=True))
                for parte in caminho.parts[1:]:
                    atual /= parte
                    if criar:
                        try:
                            atual.mkdir(mode=0o770)
                        except FileExistsError:
                            pass
                    self._handles.append(_handle_windows(atual, diretorio=True))
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                self.fd = os.open(caminho.anchor, flags)
                for parte in caminho.parts[1:]:
                    if criar:
                        try:
                            os.mkdir(parte, mode=0o770, dir_fd=self.fd)
                        except FileExistsError:
                            pass
                    filho = os.open(parte, flags, dir_fd=self.fd)
                    os.close(self.fd)
                    self.fd = filho
        except BaseException:
            self.fechar()
            raise

    @staticmethod
    def _validar_nome(nome: str) -> None:
        if not nome or nome in {".", ".."} or any(c in nome for c in "/\\\0"):
            raise ValueError("nome_local_de_midia_invalido")

    def _nome(self, nome: str) -> str | Path:
        self._validar_nome(nome)
        return self.caminho / nome if self.fd is None else nome

    def stat(self, nome: str) -> os.stat_result:
        return os.lstat(self._nome(nome), dir_fd=self.fd)

    def abrir(self, nome: str, flags: int, modo: int = 0o600) -> int:
        alvo = self._nome(nome)
        if self.fd is not None:
            return os.open(alvo, flags | os.O_NOFOLLOW | os.O_NONBLOCK, modo, dir_fd=self.fd)
        if flags & os.O_CREAT:
            # Somente criação exclusiva: nunca abrir existente/seguir link para escrever.
            if not flags & os.O_EXCL:
                raise ValueError("criacao_local_deve_ser_exclusiva")
            return os.open(alvo, flags | os.O_BINARY, modo)
        import msvcrt
        handle = _handle_windows(Path(alvo), diretorio=False)
        try:
            return msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
        except BaseException:
            self._fechar_handle(handle)
            raise

    def temporario(self, prefixo: str) -> tuple[int, str]:
        for _ in range(10):
            nome = f"{prefixo}{secrets.token_hex(16)}.tmp"
            try:
                return self.abrir(nome, os.O_RDWR | os.O_CREAT | os.O_EXCL), nome
            except FileExistsError:
                continue
        raise OSError("temporario_local_indisponivel")

    def publicar(self, temporario: str, final: str, descritor: int) -> None:
        if self.fd is not None:
            # Linux: o nome temporário pode ter sido trocado desde mkstemp/write.
            # linkat(AT_SYMLINK_FOLLOW) segue somente o handle próprio no procfs,
            # nunca um link fornecido pelo diretório compartilhado. Se o inode foi
            # desvinculado, falha explicitamente em vez de publicar outro objeto.
            os.link(f"/proc/self/fd/{descritor}", self._nome(final),
                    dst_dir_fd=self.fd, follow_symlinks=True)
        else:
            # O arquivo aberto no Windows não compartilha delete/rename; seu nome
            # permanece preso durante write/fsync/link e os ancestrais estão presos.
            os.link(self._nome(temporario), self._nome(final), follow_symlinks=False)
        escrito = os.fstat(descritor)
        publicado = self.stat(final)
        if (publicado.st_dev, publicado.st_ino) != (escrito.st_dev, escrito.st_ino):
            raise OSError("publicacao_local_incompativel")

    def remover(self, nome: str) -> None:
        os.unlink(self._nome(nome), dir_fd=self.fd)

    def listar(self) -> Iterator[str]:
        with os.scandir(self.fd if self.fd is not None else self.caminho) as entradas:
            for entrada in entradas:
                yield entrada.name

    def sincronizar(self) -> None:
        if self.fd is not None:
            os.fsync(self.fd)

    @staticmethod
    def _fechar_handle(handle: int) -> None:
        import ctypes
        from ctypes import wintypes
        fechar = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        fechar.argtypes = (wintypes.HANDLE,)
        fechar.restype = wintypes.BOOL
        fechar(handle)

    def fechar(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        for handle in reversed(self._handles):
            self._fechar_handle(handle)
        self._handles.clear()

    def __enter__(self) -> "DiretorioMidiaSeguro":
        return self

    def __exit__(self, tipo: type[BaseException] | None, erro: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.fechar()
