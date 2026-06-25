from .db import supabase


def carregar_filtros() -> list[dict]:
    res = supabase.table("filtros").select("*").eq("ativo", True).execute()
    return res.data or []


def passa_no_filtro(produto: dict, filtros: list[dict]) -> bool:
    """Sem filtros, aceita tudo. Com filtros, precisa passar em ao menos um."""
    if not filtros:
        return True

    titulo = (produto.get("titulo") or "").lower()
    preco = produto.get("preco") or 0

    for f in filtros:
        if any(b.lower() in titulo for b in (f.get("palavras_bloqueio") or [])):
            continue
        if f.get("categoria") and f["categoria"] != produto.get("categoria"):
            continue
        if f.get("preco_max") and preco > float(f["preco_max"]):
            continue
        chaves = f.get("palavras_chave") or []
        if chaves and not any(c.lower() in titulo for c in chaves):
            continue
        return True
    return False
