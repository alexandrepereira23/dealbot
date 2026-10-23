"""Logs JSON por campos permitidos, sem serializar exceções/payloads remotos."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger("dealbot")


def log(evento: str, **campos: Any) -> None:
    """Emite metadados de processamento; chamadores nunca passam texto/segredos."""
    LOGGER.info(json.dumps({"horario": datetime.now(timezone.utc).isoformat(),
                            "evento": evento, **campos}, ensure_ascii=False))


def motivo_erro(erro: BaseException) -> str:
    """Só classe/status: mensagens de SDK podem conter URLs, tokens e texto."""
    from .modelos import Aguardar, ErroPermanente
    motivos = {"midia_excede_limite", "mensagem_apagada", "produto_vinculado_removido",
               "hash_em_reconciliacao", "http_limitado", "limite_remoto"}
    if isinstance(erro, (ErroPermanente, Aguardar)) and erro.args and erro.args[0] in motivos:
        return str(erro.args[0])
    status = getattr(erro, "status_code", None)
    if status is None:
        status = getattr(getattr(erro, "response", None), "status_code", None)
    motivo = f"{type(erro).__name__}:{status}" if isinstance(status, int) else type(erro).__name__
    codigo = getattr(erro, "code", None)
    if isinstance(codigo, str) and re.fullmatch(r"(?:[0-9]{2}[A-Z0-9]{3}|PGRST[0-9]{3})", codigo):
        motivo += ":" + codigo
    return motivo
