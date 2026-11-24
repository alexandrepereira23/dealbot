"""Ensaio Linux Docker, sempre com projeto NOVO e sem ler envs de produção."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
import uuid

ORIGEM = "https://localhost:18443"
MOCK = "http://127.0.0.1:54329"
VAR_TOKEN = "DEALBOT_PREFLIGHT_TOKEN"


def aguardar(teste, descricao, prazo=50):
    limite = time.monotonic() + prazo
    while time.monotonic() < limite:
        try:
            resultado = teste()
            if resultado:
                return resultado
        except OSError:
            pass
        time.sleep(.5)
    raise RuntimeError(f"Laboratório: {descricao} não ficou pronto")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("-p", "--project-name", help="Nome de projeto Compose novo (padrão: nome aleatório)")
    args = parser.parse_args()
    projeto = args.project_name or "dealbot-etapa5-" + uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", projeto):
        parser.error("nome de projeto Compose inválido")
    if not args.playwright.is_file():
        parser.error("--playwright deve apontar para o módulo instalado")
    if not __debug__:
        parser.error("execute sem -O ou PYTHONOPTIMIZE (asserts obrigatórios)")
    with tempfile.TemporaryDirectory(prefix="dealbot-compose-") as pasta:
        ensaio(args, projeto, Path(pasta))


def ensaio(args, projeto, temporario):
    raiz = Path(__file__).resolve().parents[2]
    lab = raiz / "deploy/lab"
    env_vazio = temporario / "lab.env"
    env_vazio.touch()
    base = ["docker", "compose", "--env-file", env_vazio, "-p", projeto, "-f", lab / "compose.yaml"]
    env = dict(os.environ, DEALBOT_PLAYWRIGHT_MODULE=str(args.playwright.resolve()))
    env.pop(VAR_TOKEN, None)
    ca = temporario / "caddy-root.crt"
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=tls))

    def executar(cmd, *, check=True, capturar=False, extra=None, timeout=600):
        return subprocess.run([str(p) for p in cmd], env={**env, **(extra or {})}, cwd=raiz,
                              check=check, capture_output=capturar, timeout=timeout)

    def compose(*cmd, **kwargs):
        return executar(base + list(cmd), **kwargs)

    def leitura(url, dados=None, headers=None):
        if dados is not None:
            headers = {"Content-Type": "application/json", **(headers or {})}
        pedido = urllib.request.Request(url, data=None if dados is None else json.dumps(dados).encode(), headers=headers or {})
        with http.open(pedido, timeout=3) as resposta:
            return resposta.read()

    def controle(acao):
        leitura(MOCK + "/__lab/controle", {"acao": acao}, {"x-lab-controle": "sintetico"})

    def produtos():
        return json.loads(leitura(MOCK + "/rest/v1/produtos"))

    def extrair_ca():
        r = compose("exec", "-T", "caddy", "cat", "/data/caddy/pki/authorities/local/root.crt",
                    capturar=True, check=False, timeout=10)
        return r.stdout if r.returncode == 0 else None

    def preflight():
        sessao = json.loads(leitura(MOCK + "/auth/v1/token?grant_type=password",
            {"email": "lab@example.invalid", "password": "laboratorio123"}, {"apikey": "anon-sintetica"}))
        valido = sessao["access_token"]
        assert re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", valido, re.ASCII), "Auth sintético não devolveu um JWT"
        invalido = valido + "-invalido"
        segredos = [v.encode() for v in (valido, invalido, *valido.split(".")[:2])]
        for token, codigo, marcador in (
            (valido, 0, "token validado pelo Auth"),
            (None, 2, "token não fornecido"),
            (invalido, 1, "preflight: falhou"),
        ):
            extra = {} if token is None else {VAR_TOKEN: token}
            r = compose("exec", "-T", "-e", VAR_TOKEN, "api", "node", "src/preflight.js",
                        capturar=True, check=False, extra=extra, timeout=40)
            saida = r.stdout + r.stderr
            assert not any(segredo in saida for segredo in segredos), "Preflight vazou material do token"
            assert r.returncode == codigo and marcador.encode() in saida, (
                f"Preflight: esperado código {codigo}, obtido {r.returncode} (saída omitida)"
            )
        logs = compose("logs", "--no-color", "api", "supabase", capturar=True).stdout
        assert not any(segredo in logs for segredo in segredos), "Logs dos serviços vazaram material do token"
        print("Preflight JWT sintético: válido=0, ausente=2, inválido=1 e sem vazamento na saída/logs")
        return valido

    def fila_em(estado):
        r = compose("exec", "-T", "bot", "python", "/lab/volume.py", "--fila",
                    capturar=True, check=False, timeout=10)
        if r.returncode == 0:
            fila = json.loads(r.stdout)
            assert len(fila) <= 1, "A mesma oferta foi enfileirada mais de uma vez"
            if fila and fila[0]["estado"] == estado:
                return fila[0]
        return None

    def fingerprint():
        return compose("exec", "-T", "bot", "python", "/lab/estado.py", capturar=True, timeout=15).stdout.strip()

    def ids(*servicos):
        return {s: compose("ps", "-a", "-q", s, capturar=True).stdout.strip() for s in servicos}

    def recriar():
        servicos = ("bot", "api", "supabase")
        antes = ids(*servicos)
        assert all(antes.values()), "Serviços não estavam presentes antes da recriação"
        # SIGTERM com os prazos do Compose; a fronteira fica disponível até o bot drenar.
        compose("stop", "bot", "api")
        compose("stop", "supabase")
        codigos = executar(["docker", "inspect", "--format", "{{.State.ExitCode}}",
                           *(cid.decode() for cid in antes.values())], capturar=True).stdout.split()
        assert codigos == [b"0"] * len(servicos), "Serviço terminou com erro ao receber SIGTERM"
        compose("up", "-d", "--no-deps", "--force-recreate", "supabase")
        aguardar(lambda: leitura(MOCK + "/__lab/health"), "Supabase sintético recriado")
        depois = ids("supabase")
        assert depois["supabase"] and depois["supabase"] != antes["supabase"]
        return antes

    def religar_bot_api(antes):
        compose("up", "-d", "--no-deps", "--force-recreate", "bot", "api")
        aguardar(lambda: leitura(ORIGEM + "/api/health"), "API recriada")
        assert all(novo and novo != antes[s] for s, novo in ids("bot", "api").items())

    assert executar(["docker", "info", "--format", "{{.OSType}}"], capturar=True).stdout.strip() == b"linux"
    filtro = f"label=com.docker.compose.project={projeto}"
    for cmd in (["ps", "-aq"], ["volume", "ls", "-q"], ["network", "ls", "-q"]):
        assert not executar(["docker", *cmd, "--filter", filtro], capturar=True).stdout.strip(), (
            f"Projeto {projeto} já existe; use outro -p"
        )
    for porta in (18443, 54329):
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", porta)) != 0, f"Porta {porta} em uso; não execute laboratórios simultâneos"
    compose("config", "--quiet")
    try:
        compose("build")
        compose("up", "-d", "supabase", "api", "painel", "caddy")
        aguardar(lambda: leitura(MOCK + "/__lab/health"), "Supabase sintético")
        ca.write_bytes(aguardar(extrair_ca, "CA do Caddy"))
        tls.load_verify_locations(cafile=str(ca))
        aguardar(lambda: leitura(ORIGEM + "/api/health"), "API HTTPS")
        aguardar(lambda: leitura(ORIGEM + "/login"), "painel HTTPS")
        token = preflight()
        compose("up", "-d", "bot")
        controle("oferta")
        pendente = aguardar(lambda: fila_em("processando"), "claim inicial da fila de mídia")
        cards_pendentes = produtos()
        assert [(c["id"], c["foto_url"], c["cupom"]) for c in cards_pendentes] == [(pendente["produto_id"], None, "LAB10")]
        assert (pendente["destino"], pendente["enviado"], pendente["url"]) == ("local", 0, None)
        segunda = compose("run", "--rm", "--no-deps", "bot", "python", "/lab/bot.py", "--somente-lock",
                          check=False, capturar=True)
        assert segunda.returncode != 0 and b"BlockingIOError" in segunda.stderr, "Segunda instância não foi recusada pelo lock"
        compose("exec", "-T", "bot", "python", "/lab/volume.py", "--somente-estado")

        batch = recriar()
        assert produtos() == cards_pendentes, "Supabase não preservou o card pendente (bot ainda parado)"
        foto_mock = f"{MOCK}/__lab/foto?msg={pendente['msg_id']}"
        assert json.loads(leitura(foto_mock))["liberada"] is False
        religar_bot_api(batch)
        retomada = aguardar(lambda: fila_em("processando"), "retomada da fila de mídia após recriação")
        campos = ("produto_id", "canal_id", "msg_id", "chave", "destino", "enviado", "url")
        assert all(retomada[c] == pendente[c] for c in campos) and retomada["tentativas"] > pendente["tentativas"]
        assert produtos() == cards_pendentes, "Oferta ficou duplicada/alterada durante a retomada"
        print("Recriação com foto bloqueada: mesmo card e mesmo job de mídia reclamado no SQLite")

        executar([args.node, lab / "browser.mjs", "--oferta-pendente"], extra={"LAB_CADDY_CA": str(ca), "LAB_ORIGIN": ORIGEM})
        pronta = aguardar(lambda: fila_em("pronta"), "publicação da mídia retomada")
        url = pronta["url"]
        assert pronta["enviado"] == 1 and url == "/media/" + pendente["chave"]
        assert re.fullmatch(r"/media/[a-f0-9]{32}\.webp", url)
        antes = produtos()
        assert [(c["id"], c["foto_url"], c["cupom"]) for c in antes] == [(pendente["produto_id"], url, "LAB10")]
        imagem = leitura(ORIGEM + url)
        assert imagem[:4] == b"RIFF" and imagem[8:12] == b"WEBP"
        estado_antes = fingerprint()
        auth = {"Authorization": f"Bearer {token}"}
        api_antes = json.loads(leitura(ORIGEM + "/api/produtos", headers=auth))
        assert [(c["id"], c["foto_url"], c["cupom"]) for c in api_antes] == [(pendente["produto_id"], url, "LAB10")]
        compose("exec", "-T", "bot", "python", "/lab/volume.py")
        compose("exec", "-T", "api", "node", "/lab/volume.mjs", url)

        batch = recriar()
        assert produtos() == antes, "Supabase perdeu dados publicados (bot ainda parado)"
        religar_bot_api(batch)
        assert aguardar(lambda: fila_em("pronta"), "fila de mídia pronta após recriação") == pronta
        assert fingerprint() == estado_antes
        assert json.loads(leitura(ORIGEM + "/api/produtos", headers=auth)) == api_antes
        assert leitura(ORIGEM + url) == imagem, "Os bytes do WebP mudaram após a recriação"
        compose("exec", "-T", "bot", "python", "/lab/volume.py", "--somente-estado")
        compose("exec", "-T", "api", "node", "/lab/volume.mjs", url, "--somente-referenciada")
        compose("exec", "-T", "bot", "python", "/scripts/backup-sqlite.py", "backup", "/data/state/inbox.sqlite3", "/backup/inbox.sqlite3")
        compose("exec", "-T", "bot", "python", "/scripts/backup-sqlite.py", "restore", "/backup/inbox.sqlite3", "/backup/estado-restaurado")
        compose("exec", "-T", "bot", "python", "/lab/backup-midia.py")
        # Suíte POSIX completa em usuário não root e SDKs da imagem candidata.
        executar(["docker", "build", "--target", "testes", "-t", projeto + "-bot-testes", str(raiz / "bot")])
        executar(["docker", "run", "--rm", projeto + "-bot-testes"])
        executar(["docker", "build", "--target", "testes", "-t", projeto + "-api-testes", str(raiz / "backend")])
        executar(["docker", "run", "--rm", projeto + "-api-testes"])
        compose("--profile", "sql", "up", "-d", "postgres")
        compose("--profile", "sql", "run", "--build", "--rm", "sql")
        print("Compose Linux: smoke, UID/GID/modos, lock, JWT, mídia, SIGTERM/recriação, testes POSIX e SQL aprovados")
    finally:
        compose("--profile", "sql", "stop", check=False)
        print(f"Laboratório preservado para inspeção: projeto {projeto}; volumes não excluídos")


if __name__ == "__main__":
    main()
