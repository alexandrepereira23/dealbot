"""Extensão local por identidade estável, sem formatos de canais inventados.

Um adaptador recebe texto/contexto e devolve ambos para o extrator genérico.
O registro começa vazio: somente amostras reais saneadas justificam preenchê-lo.
IDs têm precedência sobre usernames; a função não consulta rede nem Telegram.
"""

from collections.abc import Callable

Adaptador = Callable[[str, dict], tuple[str, dict]]
ADAPTADORES_POR_ID: dict[int, Adaptador] = {}
ADAPTADORES_POR_USERNAME: dict[str, Adaptador] = {}


def selecionar_adaptador(canal_id: int | None = None, username: str = "") -> Adaptador | None:
    return ADAPTADORES_POR_ID.get(canal_id) or ADAPTADORES_POR_USERNAME.get(
        username.strip().lstrip("@").casefold()
    )
