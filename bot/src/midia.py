"""Adaptador único de mídia; download e limite de memória pertencem ao chamador."""

import asyncio
import math
import re
from typing import Any, Protocol

from .politica import configurar_limites_http


BUCKET = "produtos"


class ArmazenamentoMidia(Protocol):
    async def enviar(self, chave: str, dados: bytes) -> str: ...

    async def remover(self, chave: str) -> None: ...


class ArmazenamentoSupabase:
    def __init__(self, client: Any, timeout: float = 30) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("O timeout de mídia deve ser positivo e finito")
        self._client = client
        self._timeout = timeout
        configurar_limites_http(getattr(getattr(client, "storage", None), "session", None))

    @staticmethod
    def _validar_chave(chave: str) -> None:
        if not isinstance(chave, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", chave):
            raise ValueError("A chave de mídia deve ser plana, segura e terminar em .jpg")

    async def enviar(self, chave: str, dados: bytes) -> str:
        self._validar_chave(chave)
        if not isinstance(dados, bytes):
            raise TypeError("O adaptador de mídia aceita somente bytes")
        bucket = self._client.storage.from_(BUCKET)
        # storage3 0.8 altera file_options ao converter upsert em x-upsert.
        opcoes = {"content-type": "image/jpeg", "upsert": "true"}
        resposta = await asyncio.wait_for(
            bucket.upload(chave, dados, opcoes), timeout=self._timeout
        )
        # A API desta versão retorna HTTPX Response, não dict de metadados.
        status = getattr(resposta, "status_code", None)
        if not isinstance(status, int) or not 200 <= status < 300:
            raise RuntimeError("Upload de mídia sem confirmação do Supabase")
        url = await asyncio.wait_for(bucket.get_public_url(chave), timeout=self._timeout)
        if not isinstance(url, str) or not url.strip():
            raise RuntimeError("URL pública ausente na resposta do Storage")
        return url

    async def remover(self, chave: str) -> None:
        self._validar_chave(chave)
        dados = await asyncio.wait_for(
            self._client.storage.from_(BUCKET).remove([chave]), timeout=self._timeout
        )
        # [] também confirma remoção idempotente de um objeto já ausente.
        if not isinstance(dados, list):
            raise RuntimeError("Remoção de mídia sem confirmação do Supabase")
