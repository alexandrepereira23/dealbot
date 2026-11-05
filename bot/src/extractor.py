"""Extração local conservadora: uma oferta por mensagem, sem rede nem IA."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .adaptadores import selecionar_adaptador
from .dinheiro import em_centavos, numero_publico
from .normalizacao import contem_termo, normalizar_texto


@dataclass(frozen=True)
class ResultadoExtracao:
    produto: dict | None
    conteudo: str
    motivos: tuple[str, ...] = ()
    fonte_preco: str | None = None
    fonte_link: str | None = None


@dataclass(frozen=True)
class _TrechoOferta:
    """Derivado transitório compartilhado por preço, título e conteúdo."""

    linha: int
    texto: str
    descricao: str
    normalizada: str


_URL = re.compile(r"https?://[^\s<>`\"]+", re.IGNORECASE)
_MOEDA = re.compile(r"R\$[^\S\n]*([+-][^\S\n]*\d[\d.,]*|\d[\d.,]*)", re.IGNORECASE)
_VALOR_CONTEXTUAL = re.compile(
    r"(?<!\w)(?:por|preço(?:\s+final)?|valor|à\s+vista|a\s+vista|no\s+pix|pix)"
    r"[^\S\n]*(?:[:=][^\S\n]*)?(\d[\d.,]*)(?!\w)", re.IGNORECASE
)
_PRECO_DESCRICAO = re.compile(
    r"(?:(?<!\w)(?:pre[cç]o\s+original|pre[cç]o\s+final|[aà]\s+vista|no\s+pix|"
    r"de|por|antes(?:\s+de)?|era|agora|final|pre[cç]o|valor|pix)\s*[:=]?\s*)?" + _MOEDA.pattern,
    re.IGNORECASE,
)
_SERVICO_DESCRICAO = re.compile(
    r"(?<!\w)(?:frete|envio|entrega|parcelamento|desconto|economize|economia|cashback|"
    r"cupom|compra\s+m[ií]nima|acima\s+de)(?!\w)", re.IGNORECASE,
)
_ESPECIFICACAO = re.compile(
    r"^(?:capacidade|armazenamento|modelo|marca|cor|tamanho|variante|versao|conexao|"
    r"especificacao|especificacoes|com|possui)(?!\w)"
)
_FRETE_GRATIS = re.compile(
    r"(?<!\w)(?:(?:frete|envio|entrega)(?:\s*[:=\-–—]\s*|\s+)"
    r"(?:(?:de|por|[eé])\s+)?(?:gr[aá]tis|gratuit[oa]|gra[cç]a)|"
    r"(?:gr[aá]tis|gratuit[oa])\s+de\s+(?:frete|envio|entrega))(?!\w)", re.IGNORECASE,
)
_SERVICO_MONETARIO = re.compile(
    r"(?<!\w)(?:frete|envio|entrega|desconto|economia|economize|cashback|"
    r"compra\s+m[ií]nima|acima\s+de)\s*(?:[:=\-–—]\s*)?"
    r"(?:(?:de|por)\s*)?(?:[:=\-–—]\s*)?" + _MOEDA.pattern,
    re.IGNORECASE,
)
_PARCELA_DESCRICAO = re.compile(
    r"(?<!\w)(?:\d+\s*(?:x|vezes)|parcelas?)\s*(?:de\s*)?[:=]?\s*"
    + _MOEDA.pattern + r"(?:\s+(?:sem|com)\s+juros)?", re.IGNORECASE,
)
_MEMORIA_ESPECIFICADA = re.compile(
    r"(?:memoria(?:\s+ram)?|ram)\s*:?\s*\d+(?:[.,]\d+)?\s*(?:mb|gb|tb)"
    r"(?:\s+ddr[345])?"
)
_CAMPO_COMPONENTE = re.compile(
    r"^(?:processador|cpu|gpu|placa\s+de\s+video|"
    r"armazenamento|tela|ssd|hd)\s*:\s*\S"
)
_COMPUTADOR = re.compile(r"(?<!\w)(?:notebook|pc|computador)(?!\w)")
_FRETE_INCLUSO = re.compile(
    r"(?<!\w)(?:frete|envio|entrega)\s*(?:[:=\-–—]\s*)?"
    r"(?:[eé]\s+)?(?:inclus[oa]|inclu[ií]d[oa])(?!\w)", re.IGNORECASE,
)
# Vírgula diante de texto (inclusive entre aspas/parênteses) separa cláusula
# mesmo sem espaço; diante de número, preserva decimal/locale ambíguo.
_SEPARADOR_TRECHO = re.compile(r"\s*[;|]\s*|,\s*(?=[^\s\d])|\s+[-–—/]\s+")
_BRL = re.compile(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2})?\Z")
_CUPOM = re.compile(
    r"(?<!\w)(?:cupom|cupon|coupon)(?:[^\S\n]+de[^\S\n]+desconto)?[^\S\n]*(?:[:=\-][^\S\n]*)?"
    r"(?:[\*`_\"']{0,3})([A-Za-z0-9][A-Za-z0-9_-]{2,39})(?![\w-])", re.IGNORECASE
)
_CODIGO = re.compile(r"`{1,3}([^`\n]+)`{1,3}")
_RODAPE = re.compile(
    r"^(?:entre|entre\s+no|acesse|siga|participe|compartilhe|inscreva|nosso\s+grupo|"
    r"nosso\s+canal|mais\s+ofertas|receba\s+ofertas|grupo\s+de\s+ofertas)\b"
)
_TERMOS_CHAMADA = frozenset((
    "oferta ofertas promocao promocoes promo atencao alerta achado achados "
    "imperdivel imperdiveis super mega relampago do dia aproveite corre corram "
    "confira a o essa esta ofertaco descontaco exclusiva especial limitada hoje "
    "olha so que preco baixo"
).split())
_LINHA_SERVICO = re.compile(
    r"^(?:cupom|use\b|codigo\s+(?:de\s+)?desconto|comprar|compre|"
    r"link|confira\s+a\s+oferta|aproveite|frete|envio|parcelamento|\d+\s*x\b|"
    r"de\s+r\$|antes\b|era\b|agora\b|final\b|desconto\b|economize\b|economia\b|cashback\b|"
    r"compra\s+minima\b|acima\s+de\b|por\s+(?:r\$|\d)|a\s+vista|no\s+pix|pix\b|"
    r"preco\b|valor\b|r\$|\d+\s*%|gratis\b|gratuito\b)"
)
_SOCIAIS = frozenset({"t.me", "telegram.me", "telegram.org", "whatsapp.com", "wa.me",
                       "instagram.com", "facebook.com", "fb.com", "twitter.com", "x.com",
                       "youtube.com", "youtu.be", "discord.gg", "discord.com", "tiktok.com"})
_CATEGORIAS = {
    "eletronicos": ("notebook", "pc", "monitor", "teclado", "mouse", "headset", "fone",
                    "ssd", "hd", "placa", "processador", "memoria", "ram", "gpu", "cpu",
                    "smartphone", "celular", "tablet", "tv", "smartwatch", "roteador"),
    "games": ("game", "jogo", "ps4", "ps5", "xbox", "nintendo", "switch", "playstation", "controle", "console"),
    "casa": ("sofa", "cama", "colchao", "geladeira", "fogao", "micro-ondas", "liquidificador",
             "panela", "cadeira", "mesa", "armario", "aspirador"),
    "moda": ("tenis", "roupa", "camisa", "camiseta", "calca", "vestido", "sapato", "bolsa", "mochila", "relogio", "oculos"),
    "alimentos": ("cafe", "chocolate", "whey", "suplemento", "vitamina", "proteina", "bebida"),
    "beleza": ("perfume", "shampoo", "condicionador", "creme", "maquiagem", "skincare", "hidratante", "desodorante"),
}
_CATEGORIA_POR_TERMO = {termo: categoria for categoria, termos in _CATEGORIAS.items() for termo in termos}
_OBJETO = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in _CATEGORIA_POR_TERMO) + r")(?!\w)")


def _limpar_url(url: str) -> str | None:
    url = url.strip()
    try:
        partes = urlsplit(url)
        host = partes.hostname
        if partes.scheme.lower() not in {"http", "https"} or not host or partes.username:
            return None
        if any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
            return None
        if partes.port is not None and not 1 <= partes.port <= 65535:
            return None
        ascii_host = host.encode("idna").decode("ascii")
        if ":" not in ascii_host and not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", rotulo)
            for rotulo in ascii_host.rstrip(".").split(".")
        ):
            return None
    except (ValueError, UnicodeError):
        return None
    return url


def _chamada_generica(texto: str) -> bool:
    # Tokens evitam backtracking exponencial de repetições com espaços
    # opcionais. Uma descrição longa de produto não vira uma regex aninhada.
    tokens = re.findall(r"\w+", texto)
    return bool(tokens) and all(token in _TERMOS_CHAMADA for token in tokens)


def _social(url: str) -> bool:
    host = urlsplit(url).hostname.lower().rstrip(".")
    return any(host == dominio or host.endswith("." + dominio) for dominio in _SOCIAIS)


def _links(texto: str, contexto: dict) -> tuple[str | None, str | None, list[tuple[int, int]]]:
    candidatos = []
    spans = []
    for ordem, match in enumerate(_URL.finditer(texto)):
        bruto = match.group()
        # Só remover estrelas se o texto comprova o delimitador de abertura.
        if texto[max(0, match.start() - 2):match.start()] == "**" and bruto.endswith("**"):
            bruto = bruto[:-2]
        abertura = texto[match.start() - 1] if match.start() else ""
        fechamento = {"(": ")", "[": "]", "{": "}", "'": "'"}.get(abertura)
        if fechamento and bruto.endswith(fechamento):
            # Há delimitador de abertura fora da URL. Remover somente sua
            # contraparte; parênteses/apóstrofos do caminho/query permanecem.
            bruto = bruto[:-1]
        url = _limpar_url(bruto)
        spans.append(match.span())
        if url:
            candidatos.append((url, "texto", match.start(), ordem, ""))
    for ordem, item in enumerate(contexto.get("links", [])):
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        url = _limpar_url(item["url"])
        origem = item.get("origem")
        if origem not in {"entidade", "botao"} or not url:
            continue
        offset, tamanho = item.get("offset"), item.get("length")
        posicao = offset if isinstance(offset, int) and 0 <= offset <= len(texto) else len(texto)
        if (origem == "entidade" and isinstance(tamanho, int) and tamanho > 0
                and (_social(url) or _URL.fullmatch(str(item.get("rotulo", ""))))):
            spans.append((posicao, min(len(texto), posicao + tamanho)))
        candidatos.append((url, origem, posicao, ordem, str(item.get("rotulo", ""))))
    comerciais = [c for c in candidatos if not _social(c[0])]
    if not comerciais:
        return None, None, spans

    def prioridade(c: tuple[str, str, int, int, str]) -> tuple[int, int, int]:
        rotulo = normalizar_texto(c[4])
        compra = any(contem_termo(rotulo, p) for p in ("comprar", "compre", "produto", "oferta", "loja"))
        return (0 if compra else 1, c[2], c[3])

    escolhido = min(comerciais, key=prioridade)
    return escolhido[0], escolhido[1], spans


def _sem_spans(texto: str, spans: list[tuple[int, int]]) -> str:
    """Mascarar preserva índices e quebras de linha, inclusive em spans sobrepostos."""
    if not spans:
        return texto
    partes = []
    fim = 0
    for inicio, limite in sorted(spans):
        inicio, limite = max(fim, inicio), min(len(texto), limite)
        if limite <= inicio:
            continue
        partes.append(texto[fim:inicio])
        partes.append("".join("\n" if c == "\n" else " " for c in texto[inicio:limite]))
        fim = limite
    partes.append(texto[fim:])
    return "".join(partes)


def _spans_contexto(contexto: dict, campo: str, tamanho: int) -> list[tuple[int, int]]:
    spans = []
    for item in contexto.get(campo, []):
        if not isinstance(item, dict):
            continue
        inicio, comprimento = item.get("offset"), item.get("length")
        if isinstance(inicio, int) and isinstance(comprimento, int) and 0 <= inicio < tamanho and comprimento > 0:
            spans.append((inicio, min(tamanho, inicio + comprimento)))
    return spans


def _cupom(texto: str, contexto: dict) -> tuple[str | None, list[tuple[int, int]], list[str]]:
    codigos = []
    spans = []
    formatados = [(m.start(), m.end(), m.group(1)) for m in _CODIGO.finditer(texto)]
    formatados.extend((a, b, texto[a:b]) for a, b in _spans_contexto(contexto, "codigos", len(texto)))
    for inicio, fim, trecho in formatados:
        # Monoespaçado também pode ser produto/modelo/condição. Só omitir
        # código solto plausível, não toda descrição formatada nem "USADO".
        antes_linha = texto[texto.rfind("\n", 0, inicio) + 1:inicio]
        depois_linha = texto[fim: texto.find("\n", fim) if "\n" in texto[fim:] else len(texto)]
        if (not antes_linha.strip() and not depois_linha.strip()
                and re.fullmatch(r"[A-Za-z0-9_-]{4,40}", trecho)
                and any(c.isdigit() for c in trecho)):
            spans.append((inicio, fim))
    motivos = []
    ignorados = {"desconto", "cupom", "codigo", "aqui", "oferta", "para", "abaixo", "acima", "disponivel",
                 "indisponivel", "expirado", "automatico", "automaticamente", "aplicado", "invalido"}
    for match in _CUPOM.finditer(texto):
        codigo = match.group(1)
        spans.append(match.span())
        if normalizar_texto(codigo) not in ignorados:
            codigos.append(codigo)
    unicos = list(dict.fromkeys(codigos))
    if len(unicos) > 1:
        motivos.append("cupom_ambiguo")
        return None, spans, motivos
    if not unicos and (spans or re.search(r"\bcupom\b", texto, re.IGNORECASE)):
        motivos.append("cupom_sem_evidencia")
    return (unicos[0] if unicos else None), spans, motivos


def _papel_preco(antes: str, depois: str) -> str:
    if (re.search(r"\d+\s*(?:x|vezes)\s*(?:de\s*)?[:=]?\s*$", antes)
            or re.search(r"(?:parcela|parcelas)\s*(?:de\s*)?[:=]?\s*$", antes)):
        return "parcela"
    if (re.search(r"(?:frete|envio|entrega)\s*(?:[:=\-–—]\s*)?(?:(?:de|por)\s*)?(?:[:=\-–—]\s*)?$", antes)
            or re.match(r"\s*de\s+(?:frete|envio|entrega)\b", depois)):
        return "frete"
    if re.search(r"(?<!\w)(?:acima\s+de|a\s+partir\s+de|minim[oa](?:\s+de)?|compras\s+de)\s*$", antes):
        return "compra_minima"
    if re.search(r"(?:desconto|economize|economia|cashback|cupom)\s*(?:de\s*)?[:=]?\s*$", antes) or re.match(r"\s*(?:de\s+desconto|off\b|de\s+cashback)", depois):
        return "desconto"
    if re.search(r"(?<!\w)(?:de|antes|era|preco\s+original)\s*[:=]?\s*$", antes):
        return "anterior"
    if re.search(r"(?<!\w)(?:por|a\s+vista|(?:no\s+)?pix|final|agora)\s*[:=]?\s*$", antes) or re.match(r"\s*(?:no\s+pix|a\s+vista)\b", depois):
        return "final"
    return "generico"


def _descricao_trecho(trecho: str) -> tuple[str, str]:
    """Exclui trechos monetários/serviços, não a cauda descritiva do produto.

    Separadores delimitam cláusulas, mas todas as cláusulas descritivas são
    preservadas. Assim frete/cupom não viram termos de produto e uma condição
    depois do preço (inclusive USADO) continua disponível ao veto global.
    """
    original = trecho
    normalizada = normalizar_texto(trecho)
    if not normalizada or _RODAPE.match(normalizada) or _chamada_generica(normalizada):
        return "", ""
    comeca_servico = _SERVICO_DESCRICAO.match(trecho)
    trecho = _SERVICO_MONETARIO.sub(" ", trecho)
    trecho = _FRETE_GRATIS.sub(" ", trecho)
    trecho = _FRETE_INCLUSO.sub(" ", trecho)
    if comeca_servico and re.match(r"\s*(?:para|na\s+compra)(?!\w)", trecho, re.IGNORECASE):
        # Destino/condição do serviço não é nome de produto. Uma condição
        # residual explícita ("USADO") pode continuar na cláusula seguinte.
        return "", ""
    servico = _SERVICO_DESCRICAO.search(trecho)
    if servico:
        # O fallback só exclui esta cláusula de serviço, não as posteriores.
        trecho = trecho[:servico.start()]
    trecho = _PARCELA_DESCRICAO.sub(" ", trecho)
    trecho = _PRECO_DESCRICAO.sub(" ", trecho)
    trecho = _VALOR_CONTEXTUAL.sub(" ", trecho)
    # Serviço/preço retirado pode deixar só delimitadores decorativos. Eles
    # não são marca/modelo residual nem evidência de outro produto.
    trecho = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", " ", trecho)
    trecho = re.sub(r"\b(?:por|de|antes)\s*$", "", trecho, flags=re.IGNORECASE)
    trecho = " ".join(trecho.strip(" -:|/").split())
    if trecho != original:
        normalizada = normalizar_texto(trecho)
    if (not normalizada or _LINHA_SERVICO.match(normalizada)
            or _chamada_generica(normalizada) or not any(c.isalpha() for c in trecho)):
        return "", ""
    return trecho, normalizada


def _descricao_linha(linha: str, linha_id: int) -> list[_TrechoOferta]:
    """Prepara uma vez as cláusulas; separadores de serviço não criam objetos."""
    # Colapsar antes dos padrões evita backtracking com milhares de espaços.
    linha = " ".join(re.sub(r"[*`~_]", "", linha).split())
    linha = re.sub(r"^[^\w]+", "", linha).strip()
    linha = _FRETE_GRATIS.sub("Frete grátis", linha)
    linha = _FRETE_INCLUSO.sub("Frete incluso", linha)

    def unir_servico(match: re.Match[str]) -> str:
        texto = match.group()
        moeda = re.search(r"r\$", texto, re.IGNORECASE).start()
        # Só o prefixo: nunca mudar sinal/valor monetário capturado.
        return re.sub(r"[-–—]", ":", texto[:moeda]) + texto[moeda:]

    linha = _SERVICO_MONETARIO.sub(unir_servico, linha)
    trechos = []
    for texto in _SEPARADOR_TRECHO.split(linha):
        descricao, normalizada = _descricao_trecho(texto)
        trechos.append(_TrechoOferta(linha_id, texto, descricao, normalizada))
    return trechos


def _nomeia_produto(normalizada: str, tem_preco: bool, principal: str) -> bool:
    """Evidência local de novo objeto; especificação não cria nova identidade."""
    if (_ESPECIFICACAO.match(normalizada)
            or (not tem_preco and _MEMORIA_ESPECIFICADA.fullmatch(normalizada.strip(" .")))):
        return False
    if not tem_preco and _COMPUTADOR.search(principal) and _CAMPO_COMPONENTE.match(normalizada):
        # Rótulo de componente no computador, sem preço próprio, é campo.
        # Um processador anunciado com valor próprio continua independente.
        return False
    # Marca pode vir antes do objeto ("Logitech Headset"). O preço próprio
    # será associado a esse grupo; não usar o valor do segundo no primeiro.
    return bool(_OBJETO.search(normalizada) or re.match(r"(?:produto|item)(?!\w)", normalizada))


def _precos(texto: str, trechos: list[_TrechoOferta]) -> tuple[int | None, int | None, str | None, list[str], bool]:
    candidatos = []
    motivos = []
    grupos_com_produto = set()
    ultima_descricao = None
    descricao_atual = ""
    principal = ""
    for trecho_id, trecho in enumerate(trechos):
        linha = trecho.texto
        matches = [(m.start(), m.end(), m.group(1), m.start(1)) for m in _MOEDA.finditer(linha)]
        matches.extend((m.start(), m.end(), m.group(1), m.start(1)) for m in _VALOR_CONTEXTUAL.finditer(linha))
        matches.sort()
        valores_trecho = []
        for indice, (inicio, fim, bruto, inicio_numero) in enumerate(matches):
            anterior = matches[indice - 1][1] if indice else 0
            proximo = matches[indice + 1][0] if indice + 1 < len(matches) else len(linha)
            antes = normalizar_texto(linha[max(anterior, inicio - 100):inicio_numero].replace("R$", "").replace("r$", ""))
            # Separadores encerram o contexto de frete/parcela sem apagar de/por.
            antes = re.split(r"[/|;]", antes)[-1].strip()
            depois = normalizar_texto(linha[fim:proximo][:100])
            papel = _papel_preco(antes, depois)
            try:
                bruto = bruto.strip()
                if not _BRL.fullmatch(bruto):
                    raise ValueError("formato")
                centavos = em_centavos(bruto.replace(".", "").replace(",", "."))
            except ValueError:
                motivos.append("formato_preco_ambiguo" if not _BRL.fullmatch(bruto) else "preco_fora_da_faixa")
                continue
            valores_trecho.append((centavos, papel))
        tem_preco_proprio = any(papel in {"generico", "final"} for _, papel in valores_trecho)
        if trecho.descricao and (ultima_descricao is None or (
                _nomeia_produto(trecho.normalizada, tem_preco_proprio, principal)
                and trecho.normalizada != descricao_atual)):
            ultima_descricao = trecho_id
            descricao_atual = trecho.normalizada
            principal = trecho.normalizada
        if tem_preco_proprio and ultima_descricao is not None:
            grupos_com_produto.add(ultima_descricao)
        candidatos.extend(valores_trecho)
    finais = list(dict.fromkeys(c for c, papel in candidatos if papel == "final"))
    genericos = list(dict.fromkeys(c for c, papel in candidatos if papel == "generico"))
    anteriores = list(dict.fromkeys(c for c, papel in candidatos if papel == "anterior"))
    multiplos = len(grupos_com_produto) > 1
    if multiplos or len(finais) > 1 or (not finais and len(genericos) > 1):
        return None, None, None, motivos + ["multiplas_ofertas" if multiplos else "preco_ambiguo"], True
    atual = finais[0] if finais else (genericos[0] if genericos else None)
    fonte = "final_explicito" if finais else ("generico" if genericos else None)
    if atual is None:
        sem_frete_gratis = _FRETE_GRATIS.sub("", normalizar_texto(texto))
        if re.search(r"(?<!\w)(?:gratis|gratuito|gratuita)(?!\w)", sem_frete_gratis):
            atual, fonte = 0, "gratuidade_explicita"
    antigo = anteriores[0] if len(anteriores) == 1 else None
    if len(anteriores) > 1:
        motivos.append("preco_anterior_ambiguo")
    if antigo is not None and atual is not None and antigo <= atual:
        motivos.append("preco_anterior_inconsistente")
        antigo = None
    if atual is None:
        motivos.append("preco_desconhecido")
    return atual, antigo, fonte, motivos, False


def _descricao(trechos: list[_TrechoOferta]) -> tuple[str, str]:
    por_linha: dict[int, list[_TrechoOferta]] = {}
    for trecho in trechos:
        if trecho.descricao:
            por_linha.setdefault(trecho.linha, []).append(trecho)
    primeira = next(iter(por_linha.values()), [])
    titulo = " - ".join(t.descricao for t in primeira)
    # Preservar a fronteira das cláusulas como na descrição anterior: retirar
    # uma chamada não deve juntar palavras dispersas numa frase nova.
    conteudo = " ".join(" - ".join(t.normalizada for t in linha) for linha in por_linha.values())
    return titulo, conteudo


def _inferir_categoria(conteudo: str) -> str:
    # Primeiro objeto reconhecido, não um adjetivo gamer nem uma ocorrência na URL.
    objeto = _OBJETO.search(conteudo)
    if objeto:
        return _CATEGORIA_POR_TERMO[objeto.group()]
    return "outros"


def extrair_detalhado(texto: str, contexto: dict | None = None, *, canal_id: int | None = None,
                     username: str = "") -> ResultadoExtracao:
    contexto = contexto or {}
    adaptador = selecionar_adaptador(canal_id, username)
    if adaptador:
        texto, contexto = adaptador(texto, contexto)
    link, fonte_link, spans = _links(texto, contexto)
    texto_sem_links = _sem_spans(texto, spans + _spans_contexto(contexto, "exclusoes", len(texto)))
    cupom, codigos, motivos = _cupom(texto_sem_links, contexto)
    descritivo = _sem_spans(texto_sem_links, codigos)
    # Divulgação não participa de preço, gratuidade, categorias ou filtros.
    descritivo = "\n".join(linha for linha in descritivo.splitlines()
                            if not _RODAPE.match(normalizar_texto(linha).lstrip(" -*")))
    trechos = [trecho for linha_id, linha in enumerate(descritivo.splitlines())
               for trecho in _descricao_linha(linha, linha_id)]
    atual, anterior, fonte_preco, motivos_preco, ambiguo = _precos(descritivo, trechos)
    motivos.extend(motivos_preco)
    titulo, conteudo = _descricao(trechos)
    if ambiguo or not titulo or (atual is None and link is None):
        if not ambiguo:
            motivos.append("sem_evidencia_de_oferta")
        return ResultadoExtracao(None, conteudo, tuple(dict.fromkeys(motivos)), fonte_preco, fonte_link)
    produto = {"titulo": titulo, "preco": numero_publico(atual),
               "preco_original": numero_publico(anterior), "cupom": cupom,
               "link": link, "categoria": _inferir_categoria(conteudo)}
    return ResultadoExtracao(produto, conteudo, tuple(dict.fromkeys(motivos)), fonte_preco, fonte_link)


async def extrair_produto(texto: str, contexto: dict | None = None) -> dict | None:
    """Wrapper público antigo; diagnóstico/conteúdo nunca viram colunas remotas."""
    return extrair_detalhado(texto, contexto).produto
