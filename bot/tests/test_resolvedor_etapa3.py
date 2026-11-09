"""Rede inteiramente falsa; nenhum DNS/socket/HTTP comercial real nestes testes."""

import asyncio
import os
import socket
import ssl
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.resolvedor import ResolvedorURLs


PRODUTO = "https://www.amazon.com.br/dp/B012345678"


def resposta(status=200, headers="", corpo=b""):
    return f"HTTP/1.1 {status} Status\r\n{headers}\r\n".encode() + corpo


def registro(ip="93.184.216.34", porta=443):
    familia = socket.AF_INET6 if ":" in ip else socket.AF_INET
    endereco = (ip, porta, 0, 0) if familia == socket.AF_INET6 else (ip, porta)
    return familia, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", endereco


class LeitorFalso:
    def __init__(self, dados):
        self.dados = dados
        self.lidos = 0
        self.pedidos = []

    async def read(self, tamanho):
        self.pedidos.append(tamanho)
        dados = self.dados[self.lidos:self.lidos + tamanho]
        self.lidos += len(dados)
        return dados


class EscritorFalso:
    def __init__(self):
        self.transport = self
        self.fechado = False
        self.abortado = False
        self.enviado = b""

    def write(self, dados):
        self.enviado += dados

    async def drain(self):
        pass

    def close(self):
        self.fechado = True

    def abort(self):
        self.abortado = True


class RedeFalsa(ResolvedorURLs):
    def __init__(self, respostas=(), dns=None, **kwargs):
        super().__init__(**kwargs)
        self.respostas = list(respostas)
        self.dns = dns or {}
        self.consultas = []
        self.conexoes = []
        self.leitores = []
        self.escritores = []

    async def _dns(self, host, porta):
        self.consultas.append((host, porta))
        valor = self.dns.get(host, [registro(porta=porta)])
        if isinstance(valor, Exception):
            raise valor
        return valor

    async def _conectar(self, familia, ip, porta, host, https):
        self.conexoes.append((familia, ip, porta, host, https))
        if not self.respostas:
            raise AssertionError("Conexão inesperada; a rede deveria ter sido bloqueada")
        dados = self.respostas.pop(0)
        if isinstance(dados, Exception):
            raise dados
        leitor, escritor = LeitorFalso(dados), EscritorFalso()
        self.leitores.append(leitor)
        self.escritores.append(escritor)
        return leitor, escritor


class RedeComDNSProprio(RedeFalsa):
    """Transporte falso, mas submissão/threads/cancelamento DNS de produção."""

    _dns = ResolvedorURLs._dns


class ResolvedorDNSProprioTests(unittest.IsolatedAsyncioTestCase):
    async def aguardar(self, condicao):
        # Não usar to_thread/run_in_executor para esperar a barreira do teste:
        # queremos provar independência completa do executor default.
        async with asyncio.timeout(3):
            while not condicao():
                await asyncio.sleep(0.001)

    async def test_dns_usa_thread_propria_sem_executor_default(self):
        r = RedeComDNSProprio([resposta()])
        self.addAsyncCleanup(r.aclose)
        threads = []

        def dns_falso(*args, **kwargs):
            threads.append(threading.current_thread().name)
            return [registro()]

        loop = asyncio.get_running_loop()
        with patch("src.resolvedor.socket.getaddrinfo", side_effect=dns_falso) as dns, \
                patch.object(loop, "getaddrinfo", new=AsyncMock(side_effect=AssertionError("DNS compartilhado"))), \
                patch.object(loop, "run_in_executor", side_effect=AssertionError("Executor compartilhado")):
            self.assertEqual((await r.resolver(PRODUTO))["estado"], "positivo")
        dns.assert_called_once_with("www.amazon.com.br", 443, family=socket.AF_UNSPEC,
                                    type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].startswith("dealbot-url-dns"))
        self.assertNotEqual(threads[0], threading.current_thread().name)
        self.assertEqual(r._executor_dns._max_workers, 1)
        self.assertEqual(r.conexoes[0][1], "93.184.216.34")

    async def test_timeout_nao_libera_vaga_nem_acumula_submissoes_e_retoma(self):
        r = RedeComDNSProprio([resposta()], timeout=0.1)
        self.addAsyncCleanup(r.aclose)
        iniciou, liberar = threading.Event(), threading.Event()
        consultas = []

        def dns_falso(host, porta, **kwargs):
            consultas.append(host)
            if len(consultas) == 1:
                iniciou.set()
                if not liberar.wait(3):
                    raise AssertionError("O teste não liberou o DNS falso")
            return [registro(porta=porta)]

        with patch("src.resolvedor.socket.getaddrinfo", side_effect=dns_falso):
            try:
                primeira = asyncio.create_task(r.resolver("https://amzn.to/A"))
                await self.aguardar(iniciou.is_set)
                self.assertEqual((await primeira)["motivo"], "timeout")
                trabalho = r._dns_em_voo
                self.assertTrue(trabalho.running())
                self.assertFalse(trabalho.cancelled())
                with patch.object(r._executor_dns, "submit", wraps=r._executor_dns.submit) as submeter:
                    resultados = await asyncio.gather(*(
                        r.resolver(f"https://amzn.to/Token{i}") for i in range(25)))
                    self.assertTrue(all(resultado == {
                        "estado": "negativo", "url_final": None, "motivo": "dns_ocupado",
                    } for resultado in resultados))
                    submeter.assert_not_called()
                    self.assertIs(r._dns_em_voo, trabalho)
                    self.assertEqual(consultas, ["amzn.to"])
                    self.assertEqual(r.conexoes, [])
                    liberar.set()
                    await self.aguardar(trabalho.done)
                    # Outra URL exige outra consulta; o resultado abandonado
                    # não é cache nem pode abrir socket para o primeiro host.
                    self.assertEqual((await r.resolver(PRODUTO))["estado"], "positivo")
                    submeter.assert_called_once()
                self.assertEqual(consultas, ["amzn.to", "www.amazon.com.br"])
                self.assertEqual(len(r.conexoes), 1)
                self.assertEqual(r.conexoes[0][3], "www.amazon.com.br")
            finally:
                liberar.set()
                if r._dns_em_voo is not None:
                    await self.aguardar(r._dns_em_voo.done)

    async def test_cancelamento_externo_tambem_preserva_vaga_da_syscall(self):
        r = RedeComDNSProprio()
        self.addAsyncCleanup(r.aclose)
        iniciou, liberar = threading.Event(), threading.Event()

        def dns_falso(*args, **kwargs):
            iniciou.set()
            if not liberar.wait(3):
                raise AssertionError("O teste não liberou o DNS falso")
            return [registro("127.0.0.1")]

        with patch("src.resolvedor.socket.getaddrinfo", side_effect=dns_falso) as dns:
            try:
                tarefa = asyncio.create_task(r.resolver(PRODUTO))
                await self.aguardar(iniciou.is_set)
                tarefa.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tarefa
                trabalho = r._dns_em_voo
                self.assertTrue(trabalho.running())
                self.assertEqual((await r.resolver(PRODUTO))["motivo"], "dns_ocupado")
                dns.assert_called_once()
                self.assertEqual(r.conexoes, [])
            finally:
                liberar.set()
                if r._dns_em_voo is not None:
                    await self.aguardar(r._dns_em_voo.done)
            self.assertEqual(r.conexoes, [])

    async def test_aclose_nao_espera_syscall_nem_recria_executor(self):
        r = RedeComDNSProprio()
        self.addAsyncCleanup(r.aclose)
        iniciou, liberar, terminou = threading.Event(), threading.Event(), threading.Event()

        def dns_falso(*args, **kwargs):
            iniciou.set()
            try:
                if not liberar.wait(3):
                    raise AssertionError("O teste não liberou o DNS falso")
                return [registro()]
            finally:
                terminou.set()

        with patch("src.resolvedor.socket.getaddrinfo", side_effect=dns_falso):
            try:
                tarefa = asyncio.create_task(r.resolver(PRODUTO))
                await self.aguardar(iniciou.is_set)
                trabalho, executor = r._dns_em_voo, r._executor_dns
                with patch.object(executor, "shutdown", wraps=executor.shutdown) as encerrar:
                    await asyncio.wait_for(r.aclose(), 0.2)
                    encerrar.assert_called_once_with(wait=False, cancel_futures=True)
                self.assertTrue(tarefa.cancelled())
                self.assertTrue(trabalho.running())
                self.assertFalse(terminou.is_set())
                with patch.object(executor, "submit", wraps=executor.submit) as submeter:
                    self.assertEqual((await r.resolver(PRODUTO))["motivo"], "resolvedor_fechado")
                    submeter.assert_not_called()
                self.assertIs(r._executor_dns, executor)
                self.assertEqual(r.conexoes, [])
                await r.aclose()
            finally:
                liberar.set()
                if r._dns_em_voo is not None:
                    await self.aguardar(r._dns_em_voo.done)

    async def test_erro_dns_tardio_consumido_sem_excecao_nao_recuperada(self):
        r = RedeComDNSProprio([resposta()], timeout=0.1)
        self.addAsyncCleanup(r.aclose)
        iniciou, liberar = threading.Event(), threading.Event()
        chamadas = []
        erros_loop = []
        loop = asyncio.get_running_loop()
        anterior = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, contexto: erros_loop.append(contexto))
        self.addCleanup(loop.set_exception_handler, anterior)

        def dns_falso(*args, **kwargs):
            chamadas.append(args[0])
            if len(chamadas) == 1:
                iniciou.set()
                if not liberar.wait(3):
                    raise AssertionError("O teste não liberou o DNS falso")
                raise socket.gaierror("TOKEN_PRIVADO")
            return [registro()]

        with patch("src.resolvedor.socket.getaddrinfo", side_effect=dns_falso):
            try:
                tarefa = asyncio.create_task(r.resolver(PRODUTO))
                await self.aguardar(iniciou.is_set)
                self.assertEqual((await tarefa)["motivo"], "timeout")
                liberar.set()
                await self.aguardar(r._dns_em_voo.done)
                for _ in range(5):
                    await asyncio.sleep(0)
                self.assertEqual((await r.resolver(PRODUTO))["estado"], "positivo")
                self.assertEqual(erros_loop, [])
                self.assertEqual(len(chamadas), 2)
            finally:
                liberar.set()
                if r._dns_em_voo is not None:
                    await self.aguardar(r._dns_em_voo.done)


class ResolvedorConfiguracaoTests(unittest.TestCase):
    def test_limites_validados(self):
        for kwargs in ({"timeout": 0}, {"timeout": float("inf")}, {"timeout": float("nan")},
                       {"timeout": True}, {"max_redirects": -1}, {"max_redirects": 21},
                       {"max_redirects": True}, {"max_bytes": 0}, {"max_bytes": 1048577},
                       {"max_bytes": 2.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ResolvedorURLs(**kwargs)


class ResolvedorEtapa3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_positivo_dois_encurtadores_mesmo_destino(self):
        for inicial in ("https://amzn.to/AbC", "https://a.co/aBc", "https://meli.la/AbC"):
            r = RedeFalsa([resposta(302, f"Location: {PRODUTO}\r\n"), resposta()])
            resultado = await r.resolver(inicial)
            self.assertEqual(resultado, {"estado": "positivo", "url_final": PRODUTO,
                                         "motivo": "destino_produto_suportado"})
            self.assertEqual(len(r.conexoes), 2)
            self.assertTrue(all(e.fechado and e.abortado for e in r.escritores))

    async def test_positivo_ml(self):
        url = "https://produto.mercadolivre.com.br/MLB-1234567890"
        r = RedeFalsa([resposta()])
        self.assertEqual((await r.resolver(url))["url_final"], url)

    async def test_preserva_token_query_caixa_e_original(self):
        destino = PRODUTO + "?smid=SELLER1&tag=AbC&X=&X=2"
        r = RedeFalsa([resposta(301, f"Location: {destino}\r\n"), resposta()])
        original = "HTTPS://AMZN.TO/AbC?Sig=ToKen&x=&x=2"
        resultado = await r.resolver(original)
        self.assertEqual(resultado["url_final"], destino)
        self.assertIn(b"HEAD /AbC?Sig=ToKen&x=&x=2 HTTP/1.1", r.escritores[0].enviado)
        self.assertIn(b"?smid=SELLER1&tag=AbC&X=&X=2", r.escritores[1].enviado)
        self.assertEqual(original, "HTTPS://AMZN.TO/AbC?Sig=ToKen&x=&x=2")

    async def test_url_insegura_nunca_consulta_dns_ou_conecta(self):
        urls = ["file:///etc/passwd", "ftp://amzn.to/A", "https://user:pass@amzn.to/A",
                "https://amzn.to:80/A", "http://amzn.to:443/A", "https://amzn.to:444/A",
                "https://amzn.to./A", "https://amzn.to.evil.test/A", "https://evilamzn.to/A",
                "https://127.0.0.1/A", "https://[::1]/A", "https://2130706433/A",
                "https://amzn.to%2eevil.test/A", "https://amzn.to\\@evil.test/A",
                "https://amzn.to/A\r\nHost: evil", "https://amzn.to/ação",
                "https://amzn.to:/A", "https://amzn.to:0443/A", "https://@amzn.to/A",
                "https:///amzn.to/A", "https://amzn.to/" + "A" * 8192]
        for url in urls:
            with self.subTest(url=url[:60]):
                r = RedeFalsa()
                resultado = await r.resolver(url)
                self.assertEqual(resultado["estado"], "negativo")
                self.assertEqual(r.consultas, [])
                self.assertEqual(r.conexoes, [])
                self.assertNotIn(url, resultado["motivo"])

    async def test_todos_enderecos_dns_validos_antes_da_primeira_conexao(self):
        proibidos = ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
                     "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",
                     "192.0.2.1", "198.18.0.1", "::1", "::", "fc00::1", "fe80::1",
                     "ff02::1", "::ffff:8.8.8.8", "2002:0808:0808::1",
                     "64:ff9b::a00:1", "64:ff9b:1::a00:1", "2001:20::1", "192.0.0.9", "192.88.99.1",
                     "2001:0000:4136:e378:8000:63bf:3fff:fdd2"]
        for ip in proibidos:
            with self.subTest(ip=ip):
                r = RedeFalsa(dns={"amzn.to": [registro(), registro(ip)]})
                resultado = await r.resolver("https://amzn.to/A")
                self.assertEqual(resultado["motivo"], "dns_nao_publico")
                self.assertEqual(r.conexoes, [])

    async def test_ipv6_global_suportado(self):
        ip = "2606:4700:4700::1111"
        r = RedeFalsa([resposta()], {"www.amazon.com.br": [registro(ip)]})
        self.assertEqual((await r.resolver(PRODUTO))["estado"], "positivo")
        self.assertEqual(r.conexoes[0][:2], (socket.AF_INET6, ip))

    async def test_dns_vazio_muitos_ou_falha_sem_conexao(self):
        for valor in ([], [registro()] * 33, socket.gaierror("detalhe privado")):
            r = RedeFalsa(dns={"amzn.to": valor})
            resultado = await r.resolver("https://amzn.to/A")
            self.assertEqual(resultado["estado"], "negativo")
            self.assertEqual(r.conexoes, [])
            self.assertNotIn("privado", resultado["motivo"])

    async def test_redirect_proibido_bloqueado_antes_do_destino(self):
        destinos = ["http://169.254.169.254/latest/meta-data/", "https://evil.test/A",
                    "//127.0.0.1/A", "https://amzn.to:444/A", "file:///secret",
                    "https://user:pass@amzn.to/A", "https://amzn.to.evil.test/A"]
        for destino in destinos:
            with self.subTest(destino=destino):
                r = RedeFalsa([resposta(302, f"Location: {destino}\r\n")])
                self.assertEqual((await r.resolver("https://amzn.to/A"))["estado"], "negativo")
                self.assertEqual(len(r.conexoes), 1)
                self.assertEqual(len(r.consultas), 1)

    async def test_dns_validado_em_todo_salto_inclusive_mesmo_host(self):
        class Rebinding(RedeFalsa):
            async def _dns(self, host, porta):
                self.consultas.append((host, porta))
                return [registro()] if len(self.consultas) == 1 else [registro("127.0.0.1")]

        r = Rebinding([resposta(302, "Location: /B\r\n")])
        resultado = await r.resolver("https://amzn.to/A")
        self.assertEqual(resultado["motivo"], "dns_nao_publico")
        self.assertEqual(len(r.conexoes), 1)
        self.assertEqual(r.conexoes[0][1], "93.184.216.34")

    async def test_transporte_real_fixa_ip_tls_sni_e_nao_resolve_host(self):
        r = ResolvedorURLs()
        sock = MagicMock()
        loop = MagicMock()
        loop.sock_connect = AsyncMock()
        reader, writer = MagicMock(), MagicMock()
        with patch("src.resolvedor.socket.socket", return_value=sock), \
                patch("src.resolvedor.asyncio.get_running_loop", return_value=loop), \
                patch("src.resolvedor.asyncio.open_connection", new=AsyncMock(return_value=(reader, writer))) as abrir:
            await r._conectar(socket.AF_INET, "93.184.216.34", 443, "amzn.to", True)
        loop.sock_connect.assert_awaited_once_with(sock, ("93.184.216.34", 443))
        kwargs = abrir.await_args.kwargs
        self.assertIs(kwargs["sock"], sock)
        self.assertNotIn("host", kwargs)
        self.assertEqual(kwargs["server_hostname"], "amzn.to")
        self.assertTrue(kwargs["ssl"].check_hostname)
        self.assertEqual(kwargs["ssl"].verify_mode, ssl.CERT_REQUIRED)

    async def test_socket_fechado_quando_tls_falha_ou_cancela(self):
        for falha in (ssl.SSLCertVerificationError("privado"), asyncio.CancelledError()):
            r = ResolvedorURLs()
            sock = MagicMock()
            loop = MagicMock()
            loop.sock_connect = AsyncMock()
            with patch("src.resolvedor.socket.socket", return_value=sock), \
                    patch("src.resolvedor.asyncio.get_running_loop", return_value=loop), \
                    patch("src.resolvedor.asyncio.open_connection", new=AsyncMock(side_effect=falha)):
                with self.assertRaises(type(falha)):
                    await r._conectar(socket.AF_INET, "93.184.216.34", 443, "amzn.to", True)
            sock.close.assert_called_once()

    async def test_loop_e_hops_limitados(self):
        r = RedeFalsa([resposta(302, "Location: /B\r\n"), resposta(302, "Location: /A\r\n")])
        self.assertEqual((await r.resolver("https://amzn.to/A"))["motivo"], "loop_redirecionamento")
        self.assertEqual(len(r.conexoes), 2)
        r = RedeFalsa([resposta(302, "Location: /B\r\n")], max_redirects=0)
        self.assertEqual((await r.resolver("https://amzn.to/A"))["motivo"], "limite_redirecionamentos")
        r = RedeFalsa([resposta(302, "Location: /B\r\n"), resposta(302, "Location: /C\r\n")], max_redirects=1)
        self.assertEqual((await r.resolver("https://amzn.to/A"))["motivo"], "limite_redirecionamentos")
        self.assertEqual(len(r.conexoes), 2)

    async def test_redirect_relativo_url_produto(self):
        r = RedeFalsa([resposta(302, "Location: ../dp/B012345678?tag=AbC\r\n"), resposta()])
        resultado = await r.resolver("https://www.amazon.com.br/outro/A")
        self.assertEqual(resultado["url_final"], PRODUTO + "?tag=AbC")

    async def test_fallback_head_so_405_501_sem_corpo_mesmo_range_ignorado(self):
        for status in (405, 501):
            corpo = b"X" * 200000
            r = RedeFalsa([resposta(status), resposta(200, "Content-Length: 200000\r\n", corpo)])
            self.assertEqual((await r.resolver(PRODUTO))["estado"], "positivo")
            self.assertIn(b"HEAD ", r.escritores[0].enviado)
            self.assertIn(b"GET ", r.escritores[1].enviado)
            self.assertIn(b"Range: bytes=0-0\r\n", r.escritores[1].enviado)
            self.assertEqual(r.leitores[1].lidos, len(resposta(200, "Content-Length: 200000\r\n")))
            self.assertTrue(r.escritores[1].abortado)

    async def test_resposta_comprimida_chunked_ou_sem_tamanho_nao_le_corpo(self):
        for headers in ("Content-Encoding: gzip\r\n", "Transfer-Encoding: chunked\r\n", ""):
            r = RedeFalsa([resposta(405), resposta(200, headers, b"X" * 200000)])
            self.assertEqual((await r.resolver(PRODUTO))["estado"], "positivo")
            self.assertEqual(r.leitores[-1].lidos, len(resposta(200, headers)))
            self.assertTrue(r.escritores[-1].abortado)

    async def test_bytes_agregados_e_headers_limitados(self):
        for limite in (1, 16, 40):
            r = RedeFalsa([resposta(200, "X-Long: " + "X" * 100 + "\r\n")], max_bytes=limite)
            self.assertEqual((await r.resolver(PRODUTO))["motivo"], "limite_bytes")
            self.assertLessEqual(sum(leitor.lidos for leitor in r.leitores), limite)
            self.assertTrue(r.escritores[0].abortado)
        r = RedeFalsa([resposta(405), resposta(200, "X-Long: " + "X" * 100 + "\r\n")], max_bytes=50)
        self.assertEqual((await r.resolver(PRODUTO))["motivo"], "limite_bytes")
        self.assertEqual(sum(leitor.lidos for leitor in r.leitores), 50)
        r = RedeFalsa([resposta(200, "X-Long: " + "X" * 20000 + "\r\n")])
        self.assertEqual((await r.resolver(PRODUTO))["motivo"], "limite_bytes")
        self.assertEqual(r.leitores[0].lidos, 16384)

    async def test_fallback_revalida_dns_e_limite_exato_sem_get(self):
        head = resposta(405)
        r = RedeFalsa([head], max_bytes=len(head))
        self.assertEqual((await r.resolver(PRODUTO))["motivo"], "limite_bytes")
        self.assertEqual(len(r.conexoes), 1)
        r = RedeFalsa([resposta(405), resposta()])
        await r.resolver(PRODUTO)
        self.assertEqual(len(r.consultas), 2)

    async def test_headers_malformados_ambiguos_ou_truncados_recusados(self):
        casos = [b"HTTP/2 200 OK\r\n\r\n", b"HTTP/1.1 200 OK\r\nX: y\r\n",
                 resposta(200, "Header sem dois pontos\r\n"),
                 resposta(302, "Location: /A\r\nLocation: /B\r\n"),
                 resposta(200, "Content-Length: a\r\n"),
                 resposta(200, "Content-Length: 1\r\nTransfer-Encoding: chunked\r\n"),
                 resposta(200, " X: y\r\n"), resposta(200, "X: a\x00b\r\n"),
                 resposta(302), resposta(302, "Location: /A\tB\r\n")]
        for dados in casos:
            r = RedeFalsa([dados])
            self.assertEqual((await r.resolver(PRODUTO))["estado"], "negativo")
            self.assertTrue(all(e.fechado and e.abortado for e in r.escritores))

    async def test_status_nao_autoriza_rede_extra_nem_200_sem_identidade(self):
        for status in (400, 401, 403, 404, 429, 500, 503):
            r = RedeFalsa([resposta(status)])
            self.assertEqual((await r.resolver(PRODUTO))["motivo"], "status_nao_suportado")
            self.assertEqual(len(r.conexoes), 1)
        for url in ("https://amzn.to/A", "https://www.amazon.com.br/login", PRODUTO + "#fragmento"):
            r = RedeFalsa([resposta()])
            self.assertEqual((await r.resolver(url))["motivo"], "destino_sem_identidade")

    async def test_sem_segredos_cookies_autorizacao_proxies(self):
        destino = PRODUTO + "?tag=AbC"
        r = RedeFalsa([resposta(302, f"Location: {destino}\r\nSet-Cookie: SECRET=TOKEN\r\n"), resposta()])
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:8888", "HTTP_PROXY": "http://secret:password@localhost"}):
            self.assertEqual((await r.resolver("https://amzn.to/A"))["estado"], "positivo")
        for e in r.escritores:
            for segredo in (b"Authorization:", b"Cookie:", b"SECRET", b"TOKEN", b"Proxy-"):
                self.assertNotIn(segredo, e.enviado)

    async def test_http_porta_correspondente_sem_tls(self):
        r = RedeFalsa([resposta()])
        resultado = await r.resolver(PRODUTO.replace("https:", "http:"))
        self.assertEqual(resultado["estado"], "positivo")
        self.assertEqual(r.conexoes[0][2:], (80, "www.amazon.com.br", False))

    async def test_dns_lento_timeout_sem_conexao(self):
        class Lento(RedeFalsa):
            async def _dns(self, host, porta):
                await asyncio.Event().wait()

        r = Lento(timeout=0.02)
        self.assertEqual((await r.resolver(PRODUTO))["motivo"], "timeout")
        self.assertEqual(r.conexoes, [])

    async def test_leitura_lenta_timeout_fecha_socket(self):
        r = RedeFalsa([resposta()], timeout=0.02)
        original = r._conectar

        async def conectar(*args):
            leitor, escritor = await original(*args)

            async def bloquear(_):
                await asyncio.Event().wait()

            leitor.read = bloquear
            return leitor, escritor

        r._conectar = conectar
        self.assertEqual((await r.resolver(PRODUTO))["motivo"], "timeout")
        self.assertTrue(r.escritores[0].abortado)

    async def test_tempo_total_inclui_todos_hops_sem_orcamento_novo(self):
        class Lento(RedeFalsa):
            async def _dns(self, host, porta):
                await asyncio.sleep(0.03)
                return await super()._dns(host, porta)

        r = Lento([resposta(302, f"Location: {PRODUTO}\r\n"), resposta()], timeout=0.05)
        self.assertEqual((await r.resolver("https://amzn.to/A"))["motivo"], "timeout")
        self.assertLessEqual(len(r.conexoes), 1)

    async def test_falha_transporte_saneada_sem_retry(self):
        r = RedeFalsa([ssl.SSLCertVerificationError("URL_TOKEN_PRIVADO")])
        self.assertEqual(await r.resolver(PRODUTO), {
            "estado": "negativo", "url_final": None, "motivo": "falha_transporte"})
        self.assertEqual(len(r.conexoes), 1)

    async def test_aclose_cancela_dns_e_espera_sem_abre_rede(self):
        iniciou = asyncio.Event()

        class Bloqueado(RedeFalsa):
            async def _dns(self, host, porta):
                iniciou.set()
                await asyncio.Event().wait()

        r = Bloqueado()
        a = asyncio.create_task(r.resolver(PRODUTO))
        await iniciou.wait()
        b = asyncio.create_task(r.resolver(PRODUTO))
        await asyncio.sleep(0)
        await r.aclose()
        self.assertTrue(a.cancelled())
        self.assertTrue(b.cancelled())
        self.assertEqual(r.conexoes, [])
        self.assertEqual((await r.resolver(PRODUTO))["motivo"], "resolvedor_fechado")
        await r.aclose()

    async def test_cancelamento_externo_propagado_fecha_transporte(self):
        r = RedeFalsa([resposta()])
        iniciou = asyncio.Event()
        original = r._conectar

        async def conectar(*args):
            leitor, escritor = await original(*args)

            async def bloquear(_):
                iniciou.set()
                await asyncio.Event().wait()

            leitor.read = bloquear
            return leitor, escritor

        r._conectar = conectar
        tarefa = asyncio.create_task(r.resolver(PRODUTO))
        await iniciou.wait()
        tarefa.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await tarefa
        self.assertTrue(r.escritores[0].abortado)
        self.assertEqual(r._writers, set())
        self.assertEqual(r._tarefas, set())


if __name__ == "__main__":
    unittest.main()
