"""Ensaio Linux Docker, sempre com projeto NOVO e sem ler envs de produção."""
import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--playwright", type=Path, required=True)
    args = parser.parse_args()
    raiz = Path(__file__).resolve().parents[2]
    projeto = "dealbot-etapa5-" + uuid.uuid4().hex[:12]
    base = ["docker", "compose", "-p", projeto, "-f", str(raiz / "deploy/lab/compose.yaml")]
    env = dict(os.environ, DEALBOT_PLAYWRIGHT_MODULE=str(args.playwright))
    def executar(cmd, check=True):
        return subprocess.run([str(p) for p in cmd], env=env, cwd=raiz, check=check, timeout=600)
    def compose(*cmd, check=True):
        return executar(base + list(cmd), check)
    def leitura(url):
        with urllib.request.urlopen(url, context=ssl._create_unverified_context(), timeout=2) as r:
            return r.read()
    def aguardar(url):
        for _ in range(100):
            try:
                return leitura(url)
            except Exception:
                time.sleep(.5)
        raise RuntimeError("servico_do_laboratorio_indisponivel")
    compose("config", "--quiet")
    executar(["docker", "info", "--format", "{{.OSType}}"])
    try:
        compose("build")
        compose("run", "--rm", "preparar")
        compose("up", "-d", "supabase", "api", "painel", "caddy")
        aguardar("http://127.0.0.1:54329/__lab/health")
        aguardar("https://localhost:18443/api/health")
        aguardar("https://localhost:18443/login")
        compose("up", "-d", "bot")
        time.sleep(5)
        segunda = compose("run", "--rm", "--no-deps", "bot", "python", "/lab/bot.py", "--somente-lock", check=False)
        assert segunda.returncode != 0, "Segunda instância não foi recusada"
        executar([args.node, raiz / "deploy/lab/browser.mjs"])
        antes = json.loads(leitura("http://127.0.0.1:54329/rest/v1/produtos"))
        estado_antes = subprocess.check_output(base + ["exec", "-T", "bot", "python", "/lab/estado.py"], cwd=raiz, env=env, timeout=15)
        compose("exec", "-T", "bot", "python", "/lab/volume.py")
        compose("exec", "-T", "api", "node", "/lab/volume.mjs")
        compose("stop", "bot", "api")  # SIGTERM e prazos do Compose, sem remover volumes.
        compose("up", "-d", "--force-recreate", "bot", "api")
        aguardar("https://localhost:18443/api/health")
        time.sleep(3)
        depois = json.loads(leitura("http://127.0.0.1:54329/rest/v1/produtos"))
        estado_depois = subprocess.check_output(base + ["exec", "-T", "bot", "python", "/lab/estado.py"], cwd=raiz, env=env, timeout=15)
        assert estado_antes == estado_depois
        assert [p["id"] for p in antes] == [p["id"] for p in depois]
        assert [p["foto_url"] for p in antes] == [p["foto_url"] for p in depois]
        for p in depois:
            assert leitura("https://localhost:18443" + p["foto_url"])
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
        print("Compose Linux: smoke, UID/GID, lock, mídia, SIGTERM/recriação, testes POSIX e SQL aprovados")
    finally:
        compose("--profile", "sql", "stop", check=False)
        print(f"Laboratório preservado para inspeção: projeto {projeto}; volumes não excluídos")


if __name__ == "__main__":
    main()
