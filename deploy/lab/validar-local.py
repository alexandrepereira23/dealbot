"""Build/HTTPS/browser em checkout temporário SEM .env; não equivale a containers Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from estado import fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--frontend-build", type=Path, help="Reutilizar somente build sintético anterior sob --base")
    args = parser.parse_args()
    if not args.base.is_absolute() or not args.base.is_dir():
        raise ValueError("base_temporaria_absoluta_necessaria")
    for porta in (54329, 3333, 3000, 18443):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                raise RuntimeError("porta_ocupada_por_outro_processo")
        with socket.socket() as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("127.0.0.1", porta))  # Não reutilizar serviço já existente.
    repo = Path(__file__).resolve().parents[2]
    raiz = Path(tempfile.mkdtemp(prefix="dealbot-local-", dir=args.base))
    for nome in ("estado", "media", "caddy-data", "caddy-config"):
        (raiz / nome).mkdir(mode=0o700)
    frontend = args.frontend_build or raiz / "frontend"
    backend = raiz / "backend"
    if args.frontend_build:
        assert frontend.is_relative_to(args.base)
        assert not any(frontend.glob(".env*"))
        for nome in ("package-lock.json", "next.config.mjs"):
            assert (frontend / nome).read_bytes() == (repo / "frontend" / nome).read_bytes()
    else:
        frontend.mkdir()
    backend.mkdir()
    # Allowlist explícita: nenhum .env, SQLite ou foto do checkout entra no build.
    if not args.frontend_build:
        for nome in ("app", "components", "hooks", "lib", "public", "node_modules"):
            shutil.copytree(repo / "frontend" / nome, frontend / nome)
        for nome in ("package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts", "next.config.mjs", "eslint.config.mjs"):
            shutil.copy2(repo / "frontend" / nome, frontend / nome)
    for nome in ("src", "node_modules"):
        shutil.copytree(repo / "backend" / nome, backend / nome)
    shutil.copy2(repo / "backend/package.json", backend / "package.json")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "SUPABASE_", "NEXT_PUBLIC_", "PG", "BOT_", "MIDIA_", "LIMPEZA_", "CORS_", "RETENCAO_"))}
    env.update({"NODE_ENV": "production", "NEXT_TELEMETRY_DISABLED": "1",
        "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:54329", "NEXT_PUBLIC_SUPABASE_ANON_KEY": "anon-sintetica",
        "NEXT_PUBLIC_API_URL": "/api", "NEXT_PUBLIC_POLLING_LISTA_MS": "5000", "NEXT_PUBLIC_POLLING_STATS_MS": "30000",
        "SUPABASE_URL": "http://127.0.0.1:54329", "SUPABASE_SERVICE_KEY": "e30.e30.sintetico", "SUPABASE_ANON_KEY": "anon-sintetica",
        "CORS_ORIGIN": "https://localhost:18443", "LIMPEZA_ATIVA": "false", "MIDIA_LOCAL_DIR": str(raiz / "media"),
        "BOT_STATE_DIR": str(raiz / "estado"), "PYTHONPATH": str(repo / "bot"),
        "LAB_API_UPSTREAM": "127.0.0.1:3333", "LAB_PAINEL_UPSTREAM": "127.0.0.1:3000", "LAB_HTTPS_PORT": "18443",
        "XDG_DATA_HOME": str(raiz / "caddy-data"), "XDG_CONFIG_HOME": str(raiz / "caddy-config"),
        "DEALBOT_PLAYWRIGHT_MODULE": str(args.playwright), "PORT": "3000", "HOSTNAME": "127.0.0.1"})
    env.update({"HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "", "NO_PROXY": "*"})
    def executar(cmd, cwd):
        subprocess.run([str(p) for p in cmd], cwd=cwd, env=env, check=True, timeout=180)
    if not args.frontend_build:
        executar([args.node, "node_modules/eslint/bin/eslint.js", "."], frontend)
        executar([args.node, "node_modules/next/dist/bin/next", "build"], frontend)
        executar([args.node, "node_modules/typescript/bin/tsc", "--noEmit"], frontend)
    standalone = frontend / ".next/standalone"
    shutil.copytree(frontend / ".next/static", standalone / ".next/static", dirs_exist_ok=True)
    shutil.copytree(frontend / "public", standalone / "public", dirs_exist_ok=True)
    processos = []
    arquivos = []
    def subir(nome, cmd, cwd, extra=None):
        arquivo = (raiz / (nome + ".log")).open("wb")
        arquivos.append(arquivo)
        p = subprocess.Popen([str(p) for p in cmd], cwd=cwd, env={**env, **(extra or {})}, stdout=arquivo, stderr=subprocess.STDOUT)
        processos.append(p)
        return p
    def aguardar(url, processo):
        for _ in range(100):
            if processo.poll() is not None:
                raise RuntimeError("processo_sintetico_terminou_antes_da_prontidao")
            try:
                with urllib.request.urlopen(url, context=ssl._create_unverified_context(), timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(.2)
        raise RuntimeError("servico_sintetico_nao_iniciou")
    try:
        supabase = subir("supabase", [args.node, repo / "deploy/lab/supabase.mjs"], raiz)
        aguardar("http://127.0.0.1:54329/__lab/health", supabase)
        api = subir("api", [args.node, "src/server.js"], backend, {"PORT": "3333", "HOST": "127.0.0.1"})
        aguardar("http://127.0.0.1:3333/api/health", api)
        pedido = urllib.request.Request("http://127.0.0.1:54329/auth/v1/token", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"email": "lab@example.invalid", "password": "laboratorio123"}).encode())
        with urllib.request.urlopen(pedido, timeout=2) as r:
            token = json.load(r)["access_token"]
        subprocess.run([str(args.node), "src/preflight.js"], cwd=backend,
            env={**env, "DEALBOT_PREFLIGHT_TOKEN": token}, check=True, timeout=35)
        bot = subir("bot", [sys.executable, "-B", repo / "deploy/lab/bot.py"], raiz)
        time.sleep(3)
        if bot.poll() is not None:
            raise RuntimeError("worker_sintetico_falhou")
        segunda = subprocess.run([sys.executable, "-B", str(repo / "deploy/lab/bot.py"), "--somente-lock"], cwd=raiz, env=env, capture_output=True, timeout=10)
        assert segunda.returncode != 0, "Segunda instância não foi bloqueada"
        painel = subir("painel", [args.node, "server.js"], standalone)
        aguardar("http://127.0.0.1:3000/login", painel)
        caddy = subir("caddy", [args.caddy, "run", "--config", repo / "deploy/lab/Caddyfile", "--adapter", "caddyfile"], raiz)
        aguardar("https://localhost:18443/login", caddy)
        executar([args.node, repo / "deploy/lab/browser.mjs"], raiz)
        fotos = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (raiz / "media").glob("*.webp")}
        assert fotos
        estado_antes = fingerprint(raiz / "estado")
        for p in (bot, api):
            p.terminate()
            p.wait(timeout=15)
        print("Local: recriando bot/API após smoke", flush=True)
        bot = subir("bot-recriado", [sys.executable, "-B", repo / "deploy/lab/bot.py"], raiz)
        api = subir("api-recriada", [args.node, "src/server.js"], backend, {"PORT": "3333", "HOST": "127.0.0.1"})
        aguardar("http://127.0.0.1:3333/api/health", api)
        time.sleep(2)
        assert bot.poll() is None
        assert fotos == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (raiz / "media").glob("*.webp")}
        assert estado_antes == fingerprint(raiz / "estado")
        backups = raiz / "backups"
        backups.mkdir(mode=0o700)
        helper = repo / "deploy/scripts/backup-sqlite.py"
        executar([sys.executable, "-B", helper, "backup", raiz / "estado/inbox.sqlite3", backups / "inbox.sqlite3"], raiz)
        executar([sys.executable, "-B", helper, "restore", backups / "inbox.sqlite3", backups / "estado-restaurado"], raiz)
        assert estado_antes == fingerprint(backups / "estado-restaurado")
        with tarfile.open(backups / "media.tar.gz", "w:gz") as arquivo:
            arquivo.add(raiz / "media", arcname="media")
        with tarfile.open(backups / "media.tar.gz") as arquivo:
            arquivo.extractall(backups / "restauracao", filter="data")
        assert fotos == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (backups / "restauracao/media").glob("*.webp")}
        print("Local: segunda instância bloqueada, boot/reinício de processos e bytes WebP preservados", flush=True)
        print("Local: backup online e restauração de fila/checkpoints/mídia sintéticos aprovados", flush=True)
        print("Local: NÃO comprova SIGTERM POSIX, UID/GID, /proc/self/fd ou recriação Docker")
    finally:
        for p in reversed(processos):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        for arquivo in arquivos:
            arquivo.close()
        print(f"Artefatos sintéticos locais: {raiz}")


if __name__ == "__main__":
    main()
