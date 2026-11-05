"""Conversão exata de valores canônicos, não um parser de moeda brasileira."""

import re
from decimal import Decimal, InvalidOperation

MAX_CENTAVOS = 9_999_999_999
_CANONICO = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?\Z")


def em_centavos(valor: int | float | str | Decimal) -> int:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str, Decimal)):
        raise ValueError("valor monetário inválido")
    if isinstance(valor, str) and not _CANONICO.fullmatch(valor):
        raise ValueError("esperado decimal canônico")
    try:
        decimal = Decimal(str(valor))
        if not decimal.is_finite() or decimal < 0 or decimal > Decimal("99999999.99"):
            raise ValueError("valor monetário fora da faixa")
        partes = decimal.as_tuple()
        if partes.exponent < -2 and any(partes.digits[partes.exponent + 2:]):
            # Validar antes da multiplicação: o contexto Decimal não pode
            # arredondar uma cauda longa ou um expoente minúsculo para centavos.
            raise ValueError("precisão monetária excessiva")
        centavos = decimal * 100
        if centavos != centavos.to_integral_value():
            raise ValueError("precisão monetária excessiva")
        return int(centavos)
    except (InvalidOperation, OverflowError) as erro:
        raise ValueError("valor monetário inválido") from erro


def numero_publico(centavos: int | None) -> float | None:
    if centavos is None:
        return None
    if isinstance(centavos, bool) or not isinstance(centavos, int) or not 0 <= centavos <= MAX_CENTAVOS:
        raise ValueError("centavos inválidos")
    return centavos / 100
