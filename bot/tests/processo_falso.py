"""Processo filho offline para testar sinais/queda com estado SQLite verdadeiro."""

import asyncio
import json
import sys
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from src.sinais import sinais_encerramento
from tests.test_pipeline import StorageFake, TelegramFake, mensagem
from tests.test_repository import ClienteFake


async def executar() -> None:
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    fallback = (patch.object(loop, "add_signal_handler", side_effect=NotImplementedError)
                if sys.argv[2] == "fallback" else nullcontext())
    with fallback, sinais_encerramento(parar):
        if sys.argv[2] in ("ocioso", "fallback"):
            # Nenhum timer, worker ou SQLite pode mascarar a falta de wakeup.
            print("pronto", flush=True)
            await parar.wait()
        else:
            await executar_pipeline(parar)


async def executar_pipeline(parar: asyncio.Event) -> None:
    estado = EstadoLocal(Path(sys.argv[1]))
    await estado.abrir()
    cliente = ClienteFake()
    remoto = Path(sys.argv[1]) / "remoto_fake.json"
    if remoto.exists():
        cliente.tabelas = json.loads(remoto.read_text(encoding="utf-8"))
        cliente.proximo_id = 1 + max(linha["id"] for tabela in cliente.tabelas.values() for linha in tabela)
    repo = RepositorioSupabase(cliente)
    cache = CacheFiltros(repo)
    await cache.atualizar()
    cfg = replace(Config(), oferta_workers=1, shutdown_timeout=0.05)
    pipeline = Pipeline(estado, repo, StorageFake(), TelegramFake(), cache, cfg)
    bloqueado = asyncio.Event()
    if sys.argv[2] == "primeiro":
        salvar = repo.salvar_oferta

        async def salvar_bloqueado(*args, **kwargs):
            resultado = await salvar(*args, **kwargs)
            # Simula commit remoto cuja resposta ainda não chegou ao pipeline.
            # O segundo processo compartilha este remoto fake, não apenas SQLite.
            remoto.write_text(json.dumps(cliente.tabelas), encoding="utf-8")
            bloqueado.set()
            await asyncio.Event().wait()
            return resultado

        repo.salvar_oferta = salvar_bloqueado
        await pipeline.receber(mensagem())
    pipeline.iniciar()
    try:
        if sys.argv[2] == "primeiro":
            await bloqueado.wait()
            print("pronto", flush=True)
            await parar.wait()
        else:
            # Watchdog de teste, não timeout operacional: fsync em /mnt/c pode
            # atrasar bastante quando a simulação também exerce o disco local.
            async with asyncio.timeout(30):
                while (await estado.evento(-100111, 1))["finalizado_em"] is None:
                    await asyncio.sleep(0.005)
            print("retomado:" + str(len(cliente.tabelas["produtos"])), flush=True)
            print("aparicoes:" + str(len(cliente.tabelas["produto_aparicoes"])), flush=True)
    finally:
        try:
            inicio = time.monotonic()
            await pipeline.encerrar()
            # Mede só encerrar: o orçamento limita a espera antes de cancelar,
            # não o fsync/devolução do claim nem o fechamento do estado.
            print(f"encerramento_s:{time.monotonic() - inicio:.6f}", flush=True)
        finally:
            await estado.fechar()


if __name__ == "__main__":
    asyncio.run(executar())
