"""Processo filho offline para testar sinais/queda com estado SQLite verdadeiro."""

import asyncio
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path

from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.pipeline import Pipeline
from src.repository import RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, mensagem
from tests.test_repository import ClienteFake


async def executar() -> None:
    estado = EstadoLocal(Path(sys.argv[1]))
    await estado.abrir()
    cliente = ClienteFake()
    repo = RepositorioSupabase(cliente)
    cache = CacheFiltros(repo)
    await cache.atualizar()
    cfg = replace(Config(), oferta_workers=1, shutdown_timeout=0.05)
    pipeline = Pipeline(estado, repo, StorageFake(), TelegramFake(), cache, cfg)
    parar = asyncio.Event()
    for sinal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sinal, lambda recebido, frame: parar.set())
    if sys.argv[2] == "primeiro":
        cliente.atraso = 10
        await pipeline.receber(mensagem())
    pipeline.iniciar()
    try:
        if sys.argv[2] == "primeiro":
            while (await estado.evento(-100111, 1))["estado"] != "processando":
                await asyncio.sleep(0.005)
            print("pronto", flush=True)
            await parar.wait()
        else:
            # Watchdog de teste, não timeout operacional: fsync em /mnt/c pode
            # atrasar bastante quando a simulação também exerce o disco local.
            async with asyncio.timeout(30):
                while (await estado.evento(-100111, 1))["finalizado_em"] is None:
                    await asyncio.sleep(0.005)
            print("retomado:" + str(len(cliente.tabelas["produtos"])), flush=True)
    finally:
        await pipeline.encerrar()
        await estado.fechar()


if __name__ == "__main__":
    asyncio.run(executar())
