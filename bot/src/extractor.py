import re


def _extrair_preco(texto: str) -> tuple[float | None, float | None]:
    matches = re.findall(r"R\$\s*[\d.,]+", texto)
    precos = []
    for m in matches:
        raw = m.replace("R$", "").strip().replace(".", "").replace(",", ".")
        try:
            precos.append(float(raw))
        except ValueError:
            pass
    if not precos:
        return None, None
    if len(precos) == 1:
        return precos[0], None
    return min(precos), max(precos)


def _extrair_cupom(texto: str) -> str | None:
    padrao = re.search(
        r"(?:cupom|cupon|código|code|coupon)\s*[:\-]?\s*([A-Z0-9]{4,20})",
        texto, re.IGNORECASE,
    )
    if padrao:
        return padrao.group(1).upper()
    padrao2 = re.search(r"\b([A-Z]{3,}[0-9]{2,}|[0-9]{2,}[A-Z]{3,})\b", texto)
    return padrao2.group(1).upper() if padrao2 else None


def _extrair_link(texto: str) -> str | None:
    match = re.search(r"https?://[^\s]+", texto)
    return match.group() if match else None


def _inferir_categoria(texto: str) -> str:
    texto_lower = texto.lower()
    categorias = {
        "eletronicos": ["notebook", "pc", "monitor", "teclado", "mouse", "headset",
                        "fone", "ssd", "hd", "placa", "processador", "memória", "ram",
                        "gpu", "cpu", "smartphone", "celular", "tablet", "tv", "smart"],
        "games": ["game", "jogo", "ps4", "ps5", "xbox", "nintendo", "switch",
                  "playstation", "controle", "console"],
        "casa": ["sofá", "cama", "colchão", "geladeira", "fogão", "micro-ondas",
                 "liquidificador", "panela", "cadeira", "mesa", "armário"],
        "moda": ["tênis", "roupa", "camisa", "calça", "vestido", "sapato",
                 "bolsa", "mochila", "relógio", "óculos"],
        "alimentos": ["café", "chocolate", "whey", "suplemento", "vitamina",
                      "proteína", "bebida"],
        "beleza": ["perfume", "shampoo", "condicionador", "creme", "maquiagem",
                   "skincare", "hidratante", "desodorante"],
    }
    for categoria, palavras in categorias.items():
        if any(p in texto_lower for p in palavras):
            return categoria
    return "outros"


def _extrair_titulo(texto: str) -> str:
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]
    if not linhas:
        return "Produto sem título"
    titulo = linhas[0]
    titulo = re.sub(r"https?://\S+", "", titulo)
    titulo = re.sub(r"[^\w\s\-:/().,%\"'@#]", "", titulo, flags=re.UNICODE)
    titulo = re.sub(r"\s+", " ", titulo).strip()
    for sep in [" : ", " - ", " | "]:
        if sep in titulo:
            titulo = titulo.split(sep)[0].strip()
            break
    return titulo[:100] or "Produto sem título"


async def extrair_produto(texto: str) -> dict | None:
    if not texto or len(texto) < 20:
        return None

    preco, preco_original = _extrair_preco(texto)
    link = _extrair_link(texto)

    if not preco and not link:
        return None

    return {
        "titulo": _extrair_titulo(texto),
        "preco": preco,
        "preco_original": preco_original,
        "cupom": _extrair_cupom(texto),
        "link": link,
        "categoria": _inferir_categoria(texto),
    }