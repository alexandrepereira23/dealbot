"""Composição explícita do cliente assíncrono, sem ler ambiente na importação."""

import asyncio
import math
from typing import Any


async def criar_cliente(
    url: str, chave: str, timeout: float = 10, midia_timeout: float = 30
) -> Any:
    """Cria o cliente da versão 2.9.1 com limites de rede e de operação."""
    if any(not math.isfinite(valor) or valor <= 0 for valor in (timeout, midia_timeout)):
        raise ValueError("Os timeouts do Supabase devem ser positivos e finitos")

    # Importação tardia permite testes offline sem SDK nem credenciais.
    from supabase import AsyncClientOptions, acreate_client

    opcoes = AsyncClientOptions(
        auto_refresh_token=False,
        persist_session=False,
        postgrest_client_timeout=timeout,
        storage_client_timeout=midia_timeout,
        function_client_timeout=timeout,
    )
    cliente = await asyncio.wait_for(
        acreate_client(url, chave, options=opcoes), timeout=timeout
    )
    # 2.9.1 não expõe timeout de Auth nas opções; esse transporte é HTTPX.
    cliente.auth._http_client.timeout = timeout
    return cliente


async def fechar_cliente(client: Any) -> None:
    """Fecha transportes existentes, sem instanciar serviços lazy no shutdown.

    Em 2.9.1 não há AsyncClient.aclose: PostgREST e Storage têm aclose,
    enquanto GoTrue tem close. Tenta todos mesmo quando um deles falha.
    """
    operacoes = []
    for atributo in ("_postgrest", "_storage"):
        servico = getattr(client, atributo, None)
        if servico is not None:
            operacoes.append(asyncio.wait_for(servico.aclose(), timeout=10))
    auth = getattr(client, "auth", None)
    if auth is not None:
        operacoes.append(asyncio.wait_for(auth.close(), timeout=10))
    resultados = await asyncio.gather(*operacoes, return_exceptions=True)
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
