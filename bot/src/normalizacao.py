"""Normalização única para termos e descrição; não altera a grafia pública."""

import re
import unicodedata
from functools import lru_cache

_ACENTOS_COMUNS = re.compile(r"[\u0300-\u036f]")


def normalizar_texto(texto: str) -> str:
    # lower, não casefold: a API/tela usam Unicode toLowerCase + NFD.
    # Assim não aceitam uma regra que o cache rejeitaria como duplicada.
    decomposto = unicodedata.normalize("NFD", texto.lower())
    # Via rápida em C para texto latino; não descarta alfabetos não ASCII.
    sem_acentos = _ACENTOS_COMUNS.sub("", decomposto)
    if not sem_acentos.isascii():
        sem_acentos = "".join(c for c in sem_acentos if unicodedata.category(c) != "Mn")
    return " ".join(sem_acentos.split())


@lru_cache(maxsize=4096)
def _padrao_termo(termo: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(termo) + r"(?!\w)")


def contem_termo(texto_normalizado: str, termo_normalizado: str) -> bool:
    """Frases são contíguas; letras Unicode também contam como limites de palavra."""
    return bool(termo_normalizado and _padrao_termo(termo_normalizado).search(texto_normalizado))
