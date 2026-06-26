import unicodedata
from .db import supabase


def _normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculo para comparação."""
    return unicodedata.normalize("NFD", texto.lower()).encode("ascii", "ignore").decode()


def carregar_filtros() -> list[dict]:
    res = supabase.table("filtros").select("*").eq("ativo", True).execute()
    return res.data or []


def passa_no_filtro(produto: dict, filtros: list[dict]) -> bool:
    """Sem filtros, aceita tudo. Com filtros, precisa passar em ao menos um."""
    if not filtros:
        return True

    titulo = _normalizar(produto.get("titulo") or "")
    categoria = produto.get("categoria") or ""
    preco = produto.get("preco") or 0

    for f in filtros:
        # Bloqueio — qualquer palavra bloqueia
        bloqueios = [_normalizar(b) for b in (f.get("palavras_bloqueio") or [])]
        if any(b in titulo for b in bloqueios):
            continue

        # Categoria — se definida, precisa bater
        if f.get("categoria") and f["categoria"] != categoria:
            continue

        # Preço máximo
        if f.get("preco_max") and preco > float(f["preco_max"]):
            continue

        # Palavras-chave — se definidas, ao menos uma precisa estar no título
        chaves = [_normalizar(c) for c in (f.get("palavras_chave") or [])]
        if chaves and not any(c in titulo for c in chaves):
            continue

        return True

    return False