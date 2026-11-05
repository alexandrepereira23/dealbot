"""Último snapshot válido de filtros, independente dos consumidores de mensagens."""

import asyncio
import copy
import time
from typing import Any

from .filters import RegraPreparada, preparar_filtros
from .observabilidade import log


class CacheFiltros:
    """None significa desconhecido; [] é uma resposta válida que aceita tudo."""

    def __init__(self, repositorio: Any, timeout: float = 10) -> None:
        self.repositorio = repositorio
        self.timeout = timeout
        self._filtros: list[dict] | None = None
        self.preparados: tuple[RegraPreparada, ...] | None = None
        self.atualizado_em: float | None = None
        self.versao = 0

    @property
    def filtros(self) -> list[dict] | None:
        return self._filtros

    @filtros.setter
    def filtros(self, filtros: list[dict] | None) -> None:
        # Atribuições explícitas usadas por consumidores/testes também não
        # podem deixar o snapshot preparado fora de sincronia.
        preparados = preparar_filtros(filtros) if filtros is not None else None
        self._filtros = copy.deepcopy(filtros)
        self.preparados = preparados

    async def atualizar(self) -> None:
        """Só substitui o snapshot depois de validar a resposta completa."""
        filtros = await asyncio.wait_for(self.repositorio.carregar_filtros(), self.timeout)
        self.filtros = filtros
        self.versao += 1
        self.atualizado_em = time.time()
        log("filtros_atualizados", quantidade=len(filtros), versao=self.versao)

    def idade(self) -> float | None:
        """Idade observável do snapshot; desconhecido não é uma lista vazia."""
        return time.time() - self.atualizado_em if self.atualizado_em is not None else None
