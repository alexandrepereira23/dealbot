"""Worker sintético: pipeline, SDK HTTP, SQLite e Pillow reais; Telegram falso."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys

from PIL import Image
import httpx
from src.cache import CacheFiltros
from src.config import Config
from src.db import criar_cliente, fechar_cliente
from src.estado import EstadoLocal
from src.midia import ArmazenamentoLocal, ArmazenamentosMidia
from src.modelos import Mensagem
from src.pipeline_identidade import PipelineIdentidade
from src.repository_identidade import RepositorioIdentidade
from src.sinais import sinais_encerramento


class StorageProibido:
    def __getattr__(self, nome):
        raise AssertionError("laboratorio_nao_acessa_storage")


class ResolvedorSintetico:
    async def resolver(self, url):
        return {"estado": "negativo", "url_final": None, "motivo": "laboratorio_sem_rede_externa"}


class TelegramSintetico:
    def __init__(self, http):
        self.http = http

    async def baixar_foto(self, canal, msg, limite):
        while not (await self.http.get("/__lab/foto")).json()["liberada"]:
            await asyncio.sleep(.2)
        imagem = Image.new("RGB", (600, 300), "#2277aa")
        dados = io.BytesIO()
        imagem.save(dados, format="JPEG")
        return dados.getvalue()


async def main():
    url = os.environ.get("LAB_SUPABASE_URL", "http://127.0.0.1:54329")
    if url not in {"http://127.0.0.1:54329", "http://supabase:54329"}:
        raise ValueError("laboratorio_exige_fronteira_sintetica")
    config = replace(Config(), state_dir=Path(os.environ["BOT_STATE_DIR"]),
        midia_local_dir=Path(os.environ["MIDIA_LOCAL_DIR"]), midia_modo="local",
        shutdown_timeout=2, retry_base=.1, retry_max=.5)
    estado = EstadoLocal(config.state_dir)
    # Lock é adquirido antes de compor rede; segunda instância deve terminar aqui.
    await estado.abrir()
    if "--somente-lock" in sys.argv:
        await estado.fechar()
        return
    cliente = await criar_cliente(url, "e30.e30.sintetico", 2, 2)
    repositorio = RepositorioIdentidade(cliente)
    local = ArmazenamentoLocal(config.midia_local_dir, max_entrada=config.midia_max_bytes,
        max_pixels=config.midia_max_pixels, lado_max=config.midia_lado_max,
        max_saida=config.midia_saida_max_bytes)
    armazenamento = ArmazenamentosMidia(StorageProibido(), local)
    parar = asyncio.Event()
    try:
        await armazenamento.preparar()
        async with httpx.AsyncClient(base_url=url, timeout=2) as http:
            cache = CacheFiltros(repositorio)
            await cache.atualizar()
            pipeline = PipelineIdentidade(estado, repositorio, armazenamento, TelegramSintetico(http), cache, config,
                resolvedor=ResolvedorSintetico())
            await pipeline.preparar_legados()
            pipeline.iniciar()
            try:
                with sinais_encerramento(parar):
                    while not parar.is_set():
                        if pipeline.fatal.done():
                            raise pipeline.fatal.result()
                        for evento in (await http.get("/__lab/eventos")).json():
                            await pipeline.receber(Mensagem(-100905, evento["msg"], "sintetico",
                                "Notebook sintetico\nR$ 99,90\nhttps://www.amazon.com.br/dp/B0LAB00001",
                                datetime.now(timezone.utc).isoformat(), evento["foto"]))
                        try:
                            await asyncio.wait_for(parar.wait(), .2)
                        except asyncio.TimeoutError:
                            pass
            finally:
                await pipeline.encerrar()
    finally:
        await armazenamento.fechar()
        await fechar_cliente(cliente)
        await estado.fechar()


if __name__ == "__main__":
    asyncio.run(main())
