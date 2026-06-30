"""Fingerprint de promoções para deduplicação cross-canal.

Identidade da oferta = (link sem tracking) + preço. Sem link, cai para
título normalizado + preço. Hash curto (32 chars) para caber em índice btree.
"""
import hashlib
import re
import unicodedata
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# Params de tracking removidos antes do hash — sem eles, o mesmo link com utm
# diferente vira o mesmo produto.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "ref", "tag", "aff", "afiliado",
    "smid", "_branch_match_id", "linkCode", "language",
}


def normalizar_link(link: str | None) -> str | None:
    if not link:
        return None
    try:
        bruto = link.strip().rstrip("/")
        u = urlparse(bruto.lower())
        if not u.netloc:
            return bruto.lower()
        params = [
            (k, v) for k, v in parse_qsl(u.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        params.sort()
        return urlunparse((u.scheme, u.netloc, u.path, "", urlencode(params), ""))
    except Exception:
        return link.strip().lower()


def _normalizar_titulo(titulo: str | None) -> str:
    if not titulo:
        return ""
    sem_acento = unicodedata.normalize("NFD", titulo.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento).strip()


def gerar_hash(produto: dict) -> str:
    """Hash de identidade da promoção. Mesmo (link normalizado, preço) → mesmo hash."""
    link = normalizar_link(produto.get("link"))
    preco = produto.get("preco")
    preco_str = f"{float(preco):.2f}" if preco else ""

    if link:
        base = f"l:{link}|{preco_str}"
    else:
        base = f"t:{_normalizar_titulo(produto.get('titulo'))}|{preco_str}"

    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]
