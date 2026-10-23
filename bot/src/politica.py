"""Classificação conservadora de falhas, sem imprimir respostas das integrações."""

import random
import re
from dataclasses import dataclass
from typing import Any

from .modelos import Aguardar, ErroPermanente, ErroHTTPRemoto
from .observabilidade import motivo_erro


@dataclass(frozen=True)
class Falha:
    permanente: bool
    espera: float
    motivo: str


def classificar(erro: Exception, tentativa: int, base: float, teto: float,
                rng: Any = random) -> Falha:
    """Backoff com jitter; limites do servidor nunca são encurtados pelo teto."""
    espera = rng.uniform(base, min(teto, base * 2 ** min(max(tentativa - 1, 0), 20)))
    permanente = isinstance(erro, ErroPermanente)
    if isinstance(erro, Aguardar):
        espera = max(espera, erro.segundos)
    segundos = getattr(erro, "seconds", None)
    if isinstance(segundos, (int, float)) and segundos >= 0:
        espera = max(espera, segundos)
    codigo = str(getattr(erro, "code", ""))
    if codigo.startswith("22") or codigo in {"23502", "23514"}:
        permanente = True
    status = getattr(erro, "status_code", None)
    if codigo.isdigit() and 100 <= int(codigo) <= 599:
        status = int(codigo)
    mensagem = getattr(erro, "message", None)
    if isinstance(mensagem, dict):
        bruto = mensagem.get("statusCode", mensagem.get("status", status))
        if str(bruto).isdigit():
            status = int(bruto)
    resposta = getattr(erro, "response", None)
    if resposta is not None:
        status = getattr(resposta, "status_code", status)
        retry_after = getattr(resposta, "headers", {}).get("Retry-After")
        try:
            if retry_after:
                espera = max(espera, float(retry_after))
        except ValueError:
            # HTTP-date também é permitido pelo protocolo.
            from datetime import datetime, timezone
            from email.utils import parsedate_to_datetime
            try:
                espera = max(espera, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    # 400 pode ser PGRST204 (schema/cache/configuração corrigível), não dado ruim.
    # Só códigos de dados conhecidos acima ou formatos/tamanhos irrecuperáveis
    # podem terminalizar. 400 desconhecido preserva o trabalho para diagnóstico.
    if status in (413, 415, 422):
        permanente = True
    # Acesso/credenciais podem ser corrigidos: esperar sem apagar trabalho.
    if status in (401, 403) or type(erro).__name__ in {"ChannelPrivateError", "ChatAdminRequiredError"}:
        espera = max(espera, teto)
    return Falha(permanente, espera, motivo_erro(erro))


def configurar_limites_http(cliente: Any) -> None:
    """Preserva Retry-After antes de SDKs converterem HTTPError em erro sem headers."""
    if cliente is not None and hasattr(cliente, "event_hooks"):
        hooks = cliente.event_hooks.setdefault("response", [])
        if _limite_http not in hooks:
            hooks.append(_limite_http)


async def _limite_http(resposta: Any) -> None:
    if resposta.status_code >= 400:
        import httpx
        erro = httpx.HTTPStatusError("limite_remoto", request=resposta.request, response=resposta)
        falha = classificar(erro, 1, 1, 300)
        codigo = None
        try:
            await resposta.aread()
            dados = resposta.json()
            bruto = dados.get("code") if isinstance(dados, dict) else None
            if isinstance(bruto, str) and re.fullmatch(r"(?:[0-9]{2}[A-Z0-9]{3}|PGRST[0-9]{3})", bruto):
                codigo = bruto
        except (ValueError, UnicodeError):
            pass
        # Fechar stream antes de sair por exceção de hook; não reter conexão do pool.
        await resposta.aclose()
        # storage3 captura HTTPError dentro de request() e acessa uma variável
        # ainda não atribuída se o erro veio de hook. Usar tipo próprio saneado.
        raise ErroHTTPRemoto(resposta.status_code, falha.espera, codigo)
