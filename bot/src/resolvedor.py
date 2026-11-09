"""Resolvedor HTTP/1 limitado, sem clientes autenticados, proxies ou scraping.

Allowlist EXATA: amzn.to/a.co/meli.la e os hosts BR de Amazon/ML abaixo. Cada
salto passa novamente por validação URL/DNS. Todos os IPs retornados precisam
ser públicos, sem IPv4 mapeado/túneis IPv6. O socket conecta ao IP numérico já
validado; TLS verifica certificados e SNI usa o host original. DNS não é repetido
pelo transporte. Não há fallback inseguro nem parâmetros para desativar TLS.

HEAD primeiro; somente 405/501 permitem GET Range. Só lemos cabeçalhos, nunca
HTML, preço, JS ou corpo, inclusive comprimido. Fechamos/abortamos o transporte
após os cabeçalhos, mesmo se Range for ignorado. max_bytes limita os bytes
consumidos pela aplicação, agregados entre saltos/fallback; cabeçalhos têm teto
adicional 16KiB. asyncio/TLS/SO podem prefetchar buffers finitos antes do aborto;
max_bytes não é uma promessa sobre pacotes recebidos pela placa de rede. Nenhum
corpo é descomprimido. Content-Length não determina a quantidade lida.

Um positivo confirma apenas destino com caminho de produto suportado, não
identidade comercial/condições/conteúdo da página: chamar identificar depois.
Cookies, Authorization e URL userinfo nunca são enviados. Sem retry interno,
pool HTTP persistente ou cache: o worker durável externo governa ciclos e TTLs.
Uma instância serializa rede com semáforo; timeout inclui espera, DNS, TLS e hops.
DNS usa executor PRÓPRIO de um worker, nunca o executor default compartilhado.
Há no máximo uma submissão DNS não concluída por instância, inclusive depois de
timeout/cancelamento: outra tentativa recebe negativo recuperável ``dns_ocupado``
sem enfileirar DNS nem abrir socket. Cancelar a espera NÃO interrompe getaddrinfo
do SO. O resultado tardio não é usado para conectar nem reaproveitado como cache.
``aclose`` cancela esperas e chama shutdown(wait=False, cancel_futures=True): não
aguarda a syscall, mas a thread que já está nela só termina quando o SO retornar.
ThreadPoolExecutor mantém threads não daemon: o encerramento do interpretador
pode aguardar essa thread. Não há garantia de finalizar o processo se o DNS do
SO travar para sempre; isso exige prazo/terminação externos ao interpretador.
Limite deliberado: URLs IDN/não ASCII, slugs ML e queries ML de seleção não
interpretados aqui. Não se tenta resolver todas as lojas/encurtadores.
"""

import asyncio
import ipaddress
import math
import re
import socket
import ssl
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from urllib.parse import urljoin, urlsplit

from .identidade import normalizar_url


_LOJAS = {
    "amazon.com.br", "www.amazon.com.br", "mercadolivre.com.br",
    "www.mercadolivre.com.br", "produto.mercadolivre.com.br",
}
_HOSTS = _LOJAS | {"amzn.to", "a.co", "meli.la"}
_REDIRECTS = {301, 302, 303, 307, 308}


class _Recusa(Exception):
    """Somente código seguro; nunca contém URL ou resposta do servidor."""


def _validar_url(url: str) -> tuple[str, str, int, str]:
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise _Recusa("url_invalida")
    if any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url:
        raise _Recusa("url_invalida")
    try:
        u = urlsplit(normalizar_url(url))
        if u.scheme not in {"http", "https"} or not u.hostname or u.username is not None:
            raise _Recusa("url_invalida")
        host = u.hostname
        porta = 443 if u.scheme == "https" else 80
        if u.netloc not in {host, f"{host}:{porta}"}:
            raise _Recusa("porta_ou_host_invalido")
        if host not in _HOSTS:
            raise _Recusa("host_nao_permitido")
        alvo = (u.path or "/") + (f"?{u.query}" if "?" in url.split("#", 1)[0] else "")
        return u.scheme, host, porta, alvo
    except ValueError as exc:
        raise _Recusa("url_invalida") from exc


def _ip_publico(endereco: str) -> bool:
    try:
        ip = ipaddress.ip_address(endereco)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
        if isinstance(ip, ipaddress.IPv6Address):
            return (ip in ipaddress.ip_network("2000::/3")
                    and ip not in ipaddress.ip_network("2001::/23")
                    and not (ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip.scope_id))
        if ip in ipaddress.ip_network("192.0.0.0/24") or ip in ipaddress.ip_network("192.88.99.0/24"):
            return False
        return True
    except ValueError:
        return False


def _destino_produto(url: str) -> bool:
    u = urlsplit(url)
    if "#" in url:
        return False
    if u.hostname in {"amazon.com.br", "www.amazon.com.br"}:
        return re.fullmatch(r"/dp/[A-Z0-9]{10}/?", u.path) is not None
    return u.hostname in _LOJAS and re.fullmatch(r"/MLB-[1-9][0-9]{5,19}/?", u.path) is not None


class ResolvedorURLs:
    """Orçamento por resolução; ``aclose`` cancela/fecha trabalho em andamento."""

    def __init__(self, timeout: float = 5, max_redirects: int = 5,
                 max_bytes: int = 65536) -> None:
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout deve ser positivo e finito")
        if type(max_redirects) is not int or not 0 <= max_redirects <= 20:
            raise ValueError("max_redirects deve estar entre 0 e 20")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
            raise ValueError("max_bytes deve estar entre 1 e 1048576")
        self.timeout = float(timeout)
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes
        self._tls = ssl.create_default_context()
        self._limite = asyncio.Semaphore(1)
        self._fechado = False
        self._tarefas: set[asyncio.Task[Any]] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._executor_dns: ThreadPoolExecutor | None = None
        self._dns_em_voo: Future[list[tuple]] | None = None

    async def _dns(self, host: str, porta: int) -> list[tuple]:
        """Uma syscall por vez; timeout da espera não libera a vaga da thread."""
        if self._fechado:
            raise _Recusa("resolvedor_fechado")
        if self._dns_em_voo is not None and not self._dns_em_voo.done():
            raise _Recusa("dns_ocupado")
        # Checagem/submissão sem await: serializadas no loop dono desta instância.
        # Consultar o Future do executor, NÃO um Future asyncio cancelável, evita
        # liberar a vaga enquanto a syscall anterior ainda estiver executando.
        if self._executor_dns is None:
            self._executor_dns = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dealbot-url-dns")
        trabalho = self._executor_dns.submit(
            socket.getaddrinfo, host, porta, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        self._dns_em_voo = trabalho
        loop = asyncio.get_running_loop()
        espera: asyncio.Future[None] = loop.create_future()

        def notificar() -> None:
            if not espera.done():
                espera.set_result(None)

        def concluido(_: Future[list[tuple]]) -> None:
            # Ponte de sinalização, SEM propagar cancelamento ao executor e SEM
            # publicar erros DNS tardios num Future asyncio abandonado. Inclusive
            # asyncio.shield pode registrar essas exceções no Python 3.14.
            try:
                loop.call_soon_threadsafe(notificar)
            except RuntimeError:
                # O loop já fechou; a thread termina sem reabrir recurso algum.
                pass

        trabalho.add_done_callback(concluido)
        try:
            await espera
            return trabalho.result()
        finally:
            if trabalho.done() and self._dns_em_voo is trabalho:
                self._dns_em_voo = None

    async def _conectar(self, familia: int, ip: str, porta: int, host: str,
                        https: bool) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        sock = socket.socket(familia, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        sock.setblocking(False)
        try:
            # Endereço NUMÉRICO: loop.sock_connect não executa novo getaddrinfo.
            await asyncio.get_running_loop().sock_connect(sock, (ip, porta))
            return await asyncio.open_connection(
                sock=sock, ssl=self._tls if https else None,
                server_hostname=host if https else None, limit=min(self.max_bytes, 16384),
            )
        except BaseException:
            sock.close()
            raise

    async def _enderecos(self, host: str, porta: int) -> list[tuple[int, str]]:
        registros = await self._dns(host, porta)
        if not registros or len(registros) > 32:
            raise _Recusa("dns_invalido")
        enderecos: list[tuple[int, str]] = []
        for familia, tipo, protocolo, _, endereco in registros:
            if (familia not in {socket.AF_INET, socket.AF_INET6} or tipo != socket.SOCK_STREAM
                    or protocolo not in {0, socket.IPPROTO_TCP} or endereco[1] != porta
                    or not _ip_publico(endereco[0])
                    or (familia == socket.AF_INET6 and (len(endereco) < 4 or endereco[3] != 0))):
                raise _Recusa("dns_nao_publico")
            ip = ipaddress.ip_address(endereco[0])
            if (ip.version == 4) != (familia == socket.AF_INET):
                raise _Recusa("dns_invalido")
            enderecos.append((familia, str(ip)))
        return enderecos

    async def _requisicao(self, url: str, metodo: str, restante: int) -> tuple[int, dict[str, str], int]:
        esquema, host, porta, alvo = _validar_url(url)
        enderecos = await self._enderecos(host, porta)
        # Falhar no primeiro IP não causa retries/conexões extras ocultas.
        familia, ip = enderecos[0]
        reader, writer = await self._conectar(familia, ip, porta, host, esquema == "https")
        self._writers.add(writer)
        try:
            range_header = "Range: bytes=0-0\r\n" if metodo == "GET" else ""
            requisicao = (f"{metodo} {alvo} HTTP/1.1\r\nHost: {host}\r\n"
                          "User-Agent: Dealbot-URL/2\r\nAccept-Encoding: identity\r\n"
                          f"Connection: close\r\n{range_header}\r\n")
            writer.write(requisicao.encode("ascii"))
            await writer.drain()
            bruto = bytearray()
            teto = min(restante, 16384)
            while len(bruto) < teto:
                parte = await reader.read(1)
                if not parte:
                    raise _Recusa("cabecalho_incompleto")
                bruto.extend(parte)
                if bruto.endswith(b"\r\n\r\n"):
                    break
            else:
                raise _Recusa("limite_bytes")
            linhas = bytes(bruto[:-4]).split(b"\r\n")
            status = re.fullmatch(rb"HTTP/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e]*)?", linhas[0])
            if not status:
                raise _Recusa("status_invalido")
            headers: dict[str, str] = {}
            for linha in linhas[1:]:
                nome, separador, valor = linha.partition(b":")
                if (not separador or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", nome)
                        or any(c < 32 and c != 9 or c == 127 for c in valor)):
                    raise _Recusa("cabecalho_invalido")
                chave = nome.decode("ascii").lower()
                if chave in headers:
                    # Não interpretar ambiguidades (inclusive dois Locations).
                    raise _Recusa("cabecalho_repetido")
                headers[chave] = valor.decode("latin-1").strip(" \t")
            if "content-length" in headers and not re.fullmatch(r"[0-9]{1,20}", headers["content-length"]):
                raise _Recusa("cabecalho_invalido")
            if "content-length" in headers and "transfer-encoding" in headers:
                raise _Recusa("framing_ambiguo")
            return int(status[1]), headers, len(bruto)
        finally:
            self._writers.discard(writer)
            # Corpo não lido: abortar impede download/drenagem ilimitados/TLS wait.
            writer.close()
            writer.transport.abort()

    async def resolver(self, url: str) -> dict:
        """Retorna estado/url_final/motivo; cancelamento externo é propagado."""
        negativo = {"estado": "negativo", "url_final": None, "motivo": "resolvedor_fechado"}
        if self._fechado:
            return negativo
        tarefa = asyncio.current_task()
        if tarefa is not None:
            self._tarefas.add(tarefa)
        try:
            async with asyncio.timeout(self.timeout), self._limite:
                if self._fechado:
                    return negativo
                _validar_url(url)
                atual = normalizar_url(url)
                visitados: set[str] = set()
                restante = self.max_bytes
                redirects = 0
                while True:
                    _validar_url(atual)
                    if atual in visitados:
                        raise _Recusa("loop_redirecionamento")
                    visitados.add(atual)
                    status, headers, lidos = await self._requisicao(atual, "HEAD", restante)
                    restante -= lidos
                    if status in {405, 501}:
                        if restante <= 0:
                            raise _Recusa("limite_bytes")
                        status, headers, lidos = await self._requisicao(atual, "GET", restante)
                        restante -= lidos
                    if status in _REDIRECTS:
                        destino = headers.get("location")
                        if not destino:
                            raise _Recusa("redirect_sem_location")
                        if redirects >= self.max_redirects:
                            raise _Recusa("limite_redirecionamentos")
                        if restante <= 0:
                            raise _Recusa("limite_bytes")
                        # urljoin tolera controles no início; validar antes de juntar.
                        if any(ord(c) <= 32 or ord(c) >= 127 for c in destino) or "\\" in destino:
                            raise _Recusa("redirect_invalido")
                        atual = normalizar_url(urljoin(atual, destino))
                        redirects += 1
                        continue
                    if status not in {200, 204, 206}:
                        raise _Recusa("status_nao_suportado")
                    if not _destino_produto(atual):
                        raise _Recusa("destino_sem_identidade")
                    return {"estado": "positivo", "url_final": atual, "motivo": "destino_produto_suportado"}
        except _Recusa as exc:
            return {"estado": "negativo", "url_final": None, "motivo": str(exc)}
        except TimeoutError:
            return {"estado": "negativo", "url_final": None, "motivo": "timeout"}
        except (OSError, ValueError, UnicodeError):
            return {"estado": "negativo", "url_final": None, "motivo": "falha_transporte"}
        finally:
            if tarefa is not None:
                self._tarefas.discard(tarefa)

    async def aclose(self) -> None:
        """Fecha sockets/esperas sem aguardar getaddrinfo não interrompível do SO."""
        self._fechado = True
        if self._executor_dns is not None:
            self._executor_dns.shutdown(wait=False, cancel_futures=True)
        for writer in tuple(self._writers):
            writer.close()
            writer.transport.abort()
        tarefas = [t for t in self._tarefas if t is not asyncio.current_task()]
        for tarefa in tarefas:
            tarefa.cancel()
        if tarefas:
            await asyncio.gather(*tarefas, return_exceptions=True)
