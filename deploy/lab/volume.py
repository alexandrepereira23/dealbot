"""Executar SOMENTE no volume dedicado do laboratório Compose."""
import asyncio
import io
import os
from pathlib import Path
from PIL import Image
from src.midia import ArmazenamentoLocal


async def main():
    assert os.getuid() == 10001 and os.getgid() == 10000
    raiz = Path("/data/media")
    assert raiz.stat().st_gid == 10000 and raiz.stat().st_mode & 0o2770 == 0o2770
    local = ArmazenamentoLocal(raiz, max_entrada=10485760, max_pixels=24000000,
        lado_max=960, max_saida=358400)
    try:
        await local.preparar()
        entrada = io.BytesIO()
        Image.new("RGB", (60, 30), "#2277aa").save(entrada, format="JPEG")
        await local.enviar("f" * 32 + ".webp", entrada.getvalue())
        info = (raiz / ("f" * 32 + ".webp")).stat()
        assert info.st_gid == 10000 and info.st_mode & 0o777 == 0o640
    finally:
        await local.fechar()
    print("volume: publicação atômica como bot e modo/grupo aprovados")


asyncio.run(main())
