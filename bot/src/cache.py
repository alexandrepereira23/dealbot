"""Último snapshot válido de filtros, independente dos consumidores de mensagens."""

import asyncio
import copy
import time
from typing import Any

from .observabilidade import log


class CacheFiltros:
    """None significa desconhecido; [] é uma resposta válida que aceita tudo."""

    def __init__(self, repositorio: Any, timeout: float = 10) -> None:
        self.repositorio = repositorio
        self.timeout = timeout
        self.filtros: list[dict] | None = None
        self.atualizado_em: float | None = None
        self.versao = 0

    async def atualizar(self) -> None:
        """Só substitui o snapshot depois de validar a resposta completa."""
        filtros = await asyncio.wait_for(self.repositorio.carregar_filtros(), self.timeout)
        if not isinstance(filtros, list) or any(not isinstance(f, dict) for f in filtros):
            raise ValueError("resposta_filtros_invalida")
        for filtro in filtros:
            for campo in ("palavras_chave", "palavras_bloqueio"):
                valor = filtro.get(campo)
                if valor is not None and (not isinstance(valor, list) or any(not isinstance(v, str) for v in valor)):
                    raise ValueError("resposta_filtros_invalida")
            if filtro.get("preco_max") is not None:
                float(filtro["preco_max"])
        self.filtros = copy.deepcopy(filtros)
        self.versao += 1
        self.atualizado_em = time.time()
        log("filtros_atualizados", quantidade=len(filtros), versao=self.versao)

    def idade(self) -> float | None:
        """Idade observável do snapshot; desconhecido não é uma lista vazia."""
        return time.time() - self.atualizado_em if self.atualizado_em is not None else None
