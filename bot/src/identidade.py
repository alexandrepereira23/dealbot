"""Identidade v2 conservadora, pura e independente do hash legado.

Fontes conceituais (PRD etapa 3): modelo oficial Amazon Catalog Items 2022-04-01
(ASIN não prova seller/variante) e documentação Mercado Livre ``/pt_br/variacoes``
(item, seller, catálogo e variação são conceitos distintos). Subconjunto sintático:
Amazon BR ``/dp/ASIN`` e ML BR ``/MLB-<número>`` (sem slug). Não se afirma que
todas as URLs públicas, queries ou seleções dessas lojas sejam suportadas.

``contexto['identidade']`` é evidência explícita do chamador, NÃO defaults de
configuração: campos abaixo recebem string/int positivo ou um objeto
``{estado: 'conhecido', valor: ..., fonte: '...'}``; não aplicabilidade exige
``{estado: 'nao_aplicavel', motivo: 'prova ...'}``. Ausência/null é desconhecido.
Também são aceitas linhas completas ``Vendedor: ...``, ``Variante: ...`` etc.
Essas declarações devem descrever a oferta selecionada, não todo o catálogo.
O chamador não deve inventar essas declarações a partir de campos ausentes.

Somente ``tag`` (caixa EXATA) é descartado como tracking no formato Amazon
aceito, com todos os demais campos comprovados: é um identificador do programa
Associates, não vendedor (Amazon Associates, "Linking Requirements", seção
Special Links: https://affiliate-program.amazon.com/help/operating/linking).
Não se estende essa regra a ``ref``, ``smid``, UTM, grafias diferentes, fragmentos,
links assinados ou outros hosts. ``linkCode`` tem comparação com caixa exata e
é CONSERVADO na comparação: a fonte conceitual não comprova equivalência de seus
valores públicos. ``smid`` é apenas candidato: exige confirmação
explícita de vendedor. Queries ML não são interpretadas; seleção é declarada.

``componentes['comparacao']`` é o JSON canônico que o SQL deve comparar ALÉM do
hash; ``campos/evidencias/conflitos`` conservam proveniência sem participar do
hash. Nunca registrar esses objetos/URLs/cupons completos em logs públicos.
Limite deliberado: não é um leitor geral de linguagem natural. Restrições livres
detectáveis não interpretadas impedem chave; mensagens sem evidência estruturada
continuam provisórias. Preço, título e imagem nunca geram identidade.
"""

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from .dinheiro import em_centavos


_CAMPOS = (
    "loja", "produto", "anuncio", "vendedor", "sku", "variante", "estado",
    "quantidade", "kit", "elegibilidade", "pagamento", "cupom", "restricoes",
    "frete", "assinatura", "cor", "capacidade", "tamanho", "voltagem",
)
_OBRIGATORIOS = _CAMPOS[:15]
_ROTULOS = {
    "Produto": "produto", "Anuncio": "anuncio", "Anúncio": "anuncio",
    "Vendedor": "vendedor", "SKU": "sku", "Variante": "variante",
    "Estado": "estado", "Quantidade": "quantidade", "Kit": "kit",
    "Elegibilidade": "elegibilidade", "Pagamento": "pagamento", "Cupom": "cupom",
    "Restricoes": "restricoes", "Restrições": "restricoes", "Frete": "frete",
    "Assinatura": "assinatura", "Cor": "cor", "Capacidade": "capacidade",
    "Tamanho": "tamanho", "Voltagem": "voltagem",
}
_RESTRICAO_LIVRE = re.compile(
    r"\b(?:pix|boleto|cart[aã]o|parcelad[oa]|prime|app|cupom|primeira\s+compra|"
    r"novos?\s+clientes?|assinatura|recorrente|cashback|clube|frete|retirada|"
    r"somente|exclusiv[oa]|restri[cç][aã]o|usad[oa]|recondicionad[oa]|"
    r"vendido|vendedor|variante|sku|cor|tamanho|capacidade|voltagem|kit|quantidade|"
    r"preto|preta|azul|branco|branca|vermelho|vermelha|verde|rosa|"
    r"(?:\d+)\s*(?:unidades?|pe[cç]as?|gb|tb|ml|kg|volts?)\b)", re.IGNORECASE,
)
_AMAZON = {"amazon.com.br", "www.amazon.com.br"}
_ML = {"mercadolivre.com.br", "www.mercadolivre.com.br", "produto.mercadolivre.com.br"}


def normalizar_url(url: str) -> str:
    """Muda somente esquema/host ASCII; preserva inclusive delimitadores vazios.

    Não usa parse_qsl/urlencode nem reconstrói path/query/fragmento. Entrada
    malformada é devolvida intacta (normalização não é validação de rede).
    """
    if not isinstance(url, str):
        raise TypeError("url deve ser string")
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)(.*)", url, re.DOTALL)
    if not match or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        return url
    esquema, autoridade, restante = match.groups()
    # Userinfo pode conter tokens sensíveis à caixa: não alterar nada nesse caso.
    if "@" in autoridade or "\\" in autoridade or "%" in autoridade:
        return url
    return f"{esquema.lower()}://{autoridade.lower()}{restante}"


def _formato(url: str) -> tuple[str | None, dict[str, str], str | None]:
    """Reconhece só caminhos exatos; conserva origem, barra e query restantes."""
    if len(url) > 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url:
        return None, {}, "url_invalida"
    try:
        u = urlsplit(url)
        if u.scheme not in {"http", "https"} or u.username is not None or not u.hostname:
            return None, {}, "url_invalida"
        host = u.hostname
        if u.netloc not in {host, f"{host}:{80 if u.scheme == 'http' else 443}"}:
            return None, {}, "url_invalida"
        erro_fragmento = "fragmento_nao_suportado" if "#" in url else None
        origem = f"{u.scheme}://{u.netloc}"
        amazon = re.fullmatch(r"/dp/([A-Z0-9]{10})(/?)", u.path)
        ml = re.fullmatch(r"/(MLB-[1-9][0-9]{5,19})(/?)", u.path)
        if host in _AMAZON and amazon:
            dados = {"loja": host, "produto": amazon[1], "origem": origem, "path": u.path}
            restantes: list[str] = []
            sellers: list[str] = []
            erro_query = None
            for parte in u.query.split("&") if u.query else []:
                nome, igual, valor = parte.partition("=")
                if nome == "tag" and igual and re.fullmatch(r"[A-Za-z0-9_-]+", valor):
                    continue
                if nome == "smid" and igual and re.fullmatch(r"[A-Z0-9]{1,32}", valor):
                    sellers.append(valor)
                elif not (nome == "linkCode" and igual and re.fullmatch(r"[A-Za-z0-9_-]+", valor)):
                    erro_query = "query_nao_suportada"
                restantes.append(parte)
            if len(sellers) > 1:
                erro_query = "seller_repetido"
            if sellers:
                dados["seller_url"] = sellers[0]
            # Inclui a query não tracking sem ordenar/decodificar e '?' vazio.
            dados["query"] = "&".join(restantes)
            dados["query_vazia_explicita"] = "sim" if "?" in url and not u.query else "nao"
            return "amazon_dp_v1", dados, erro_fragmento or erro_query
        if host in _ML and ml:
            dados = {"loja": host, "produto": ml[1], "anuncio": ml[1],
                     "origem": origem, "path": u.path, "query": u.query,
                     "query_vazia_explicita": "sim" if "?" in url and not u.query else "nao"}
            return "ml_item_v1", dados, erro_fragmento or ("query_nao_suportada" if u.query else None)
    except ValueError:
        return None, {}, "url_invalida"
    return None, {}, "formato_nao_suportado"


def _declaracao(valor: Any, fonte: str) -> dict[str, Any] | None:
    origem_declarada = None
    if isinstance(valor, dict):
        if set(valor) - {"estado", "valor", "fonte", "motivo"}:
            return None
        if isinstance(valor.get("fonte"), str):
            origem_declarada = valor["fonte"][:1024]
        estado = valor.get("estado")
        if (estado == "nao_aplicavel" and isinstance(valor.get("motivo"), str)
                and 0 < len(valor["motivo"].strip()) <= 1024 and valor.get("valor") is None):
            return {"estado": estado, "valor": None, "fonte": fonte, "motivo": valor["motivo"],
                    "origem_declarada": origem_declarada}
        if estado != "conhecido":
            return None
        valor = valor.get("valor")
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        return None
    valor = str(valor).strip()
    if (not valor or len(valor) > 1024 or valor.casefold() in {
        "desconhecido", "desconhecida", "unknown", "nao informado", "não informado",
        "nao aplicavel", "não aplicável", "n/a", "null", "none", "?",
        "padrao", "padrão", "default", "indefinido", "indefinida",
    }):
        return None
    return {"estado": "conhecido", "valor": valor, "fonte": fonte,
            "origem_declarada": origem_declarada}


_MARCADOR_COMPRA = "<<DEALBOT_LINK_COMPRA_V1>>"
_URL_TEXTO = re.compile(r"https?://[^\s<>`\"]+", re.IGNORECASE)


def _publicacao_copia(produto: dict, texto: str, contexto: dict,
                      regra: str | None, dados: dict, campos: dict,
                      conflitos: list, problemas: list) -> dict | None:
    """Cópia literal, não equivalência comercial. Não usa título nem rede.

    Apenas CRLF vira LF. O destino é o resultado exato de ``_formato``; somente
    a tag Amazon já comprovada é retirada. A única ligação de compra é marcada
    no texto/contexto, conservando rótulos ocultos, ordem, outros links, códigos,
    exclusões e declarações parciais. Proveniência das provas não entra no hash.
    Falta de provas comerciais não é conflito, mas uma declaração inválida é.
    """
    if not regra or conflitos or any(p != "restricao_textual_nao_interpretada"
                                    and p != "campo_nao_suportado" for p in problemas):
        return None
    if not isinstance(texto, str) or not texto.strip() or _MARCADOR_COMPRA in texto:
        return None
    try:
        preco = em_centavos(produto.get("preco"))
    except ValueError:
        return None
    original = produto.get("link")
    if not isinstance(original, str) or not original:
        return None
    # Resolução não pode apagar seleção/query de uma URL comercial já legível.
    normalizada = normalizar_url(original)
    regra_original, dados_originais, erro_original = _formato(normalizada)
    if regra_original:
        if erro_original or regra_original != regra or dados_originais != dados:
            return None
    else:
        if erro_original != "formato_nao_suportado":
            return None
        try:
            u = urlsplit(normalizada)
            if (u.scheme not in {"http", "https"} or u.netloc not in {"amzn.to", "a.co", "meli.la"}
                    or "?" in normalizada or "#" in normalizada
                    or not re.fullmatch(r"/[A-Za-z0-9_-]+/?", u.path)):
                return None
        except ValueError:
            return None
    # JSON é também a fronteira de entrada: não mutar contexto nem tolerar NaN.
    try:
        apresentacao = json.loads(json.dumps(contexto, ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError):
        return None
    declaradas = apresentacao.pop("identidade", {})
    if not isinstance(declaradas, dict):
        return None
    declaracoes = {}
    for campo, valor in declaradas.items():
        if valor is None:
            declaracoes[campo] = {"estado": "desconhecido", "valor": None}
            continue
        prova = _declaracao(valor, "contexto")
        if prova is None:
            return None
        declaracoes[campo] = {k: prova[k] for k in ("estado", "valor", "motivo") if k in prova}

    links = apresentacao.get("links", [])
    if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
        return None
    # Uma entidade visível que cobre exatamente a ocorrência não é uma segunda
    # ligação. Duas ocorrências, entidades ocultas ou botões, entretanto, são.
    visiveis = set()
    for match in _URL_TEXTO.finditer(texto):
        token = match.group()
        if token.startswith(original) and all(c in ").,;!" for c in token[len(original):]):
            visiveis.add((match.start(), match.start() + len(original)))
    ligacoes = {("texto", inicio, fim) for inicio, fim in visiveis}
    selecionados = []
    for indice, link in enumerate(links):
        if link.get("url") != original:
            continue
        origem = link.get("origem")
        if origem == "entidade":
            inicio, tamanho = link.get("offset"), link.get("length")
            if (type(inicio) is not int or type(tamanho) is not int or inicio < 0 or tamanho <= 0
                    or inicio + tamanho > len(texto) or link.get("rotulo") != texto[inicio:inicio + tamanho]):
                return None
            fim = inicio + tamanho
            ligacoes.add(("texto" if (inicio, fim) in visiveis else "entidade", inicio, fim))
        elif origem == "botao" and isinstance(link.get("rotulo"), str):
            ligacoes.add(("botao", indice))
        else:
            return None
        selecionados.append(indice)
    if len(ligacoes) != 1:
        return None
    ligacao = next(iter(ligacoes))
    trecho = (ligacao[1], ligacao[2]) if ligacao[0] == "texto" else None

    def normalizar_texto_copia(valor: str) -> str:
        return valor.replace("\r\n", "\n")

    def fronteira(posicao: int) -> int:
        if trecho:
            inicio, fim = trecho
            if inicio < posicao < fim:
                raise ValueError("span_intersecta_compra")
            if posicao >= fim:
                return (len(normalizar_texto_copia(texto[:inicio])) + len(_MARCADOR_COMPRA)
                        + len(normalizar_texto_copia(texto[fim:posicao])))
        return len(normalizar_texto_copia(texto[:posicao]))

    def ajustar_spans(valor: Any) -> None:
        if isinstance(valor, dict):
            if "offset" in valor or "length" in valor:
                inicio, tamanho = valor.get("offset"), valor.get("length")
                if (type(inicio) is not int or type(tamanho) is not int or inicio < 0
                        or tamanho <= 0 or inicio + tamanho > len(texto)):
                    raise ValueError("span_invalido")
                valor["offset"] = fronteira(inicio)
                valor["length"] = fronteira(inicio + tamanho) - fronteira(inicio)
            for filho in valor.values():
                ajustar_spans(filho)
        elif isinstance(valor, list):
            for filho in valor:
                ajustar_spans(filho)

    for indice in selecionados:
        link = links[indice]
        link["url"] = _MARCADOR_COMPRA
        if trecho and link.get("origem") == "entidade":
            link["rotulo"] = _MARCADOR_COMPRA
    try:
        ajustar_spans(apresentacao)
    except ValueError:
        return None
    if trecho:
        inicio, fim = trecho
        conteudo = texto[:inicio] + _MARCADOR_COMPRA + texto[fim:]
    else:
        conteudo = texto
    # Só URL não é conteúdo substantivo. Botão/rótulo não substitui o post bruto.
    substantivo = texto[:trecho[0]] + texto[trecho[1]:] if trecho else texto
    if not _URL_TEXTO.sub("", substantivo).strip():
        return None
    comparacao = {"destino": {"regra": regra, **dados},
                  "conteudo": normalizar_texto_copia(conteudo), "preco_centavos": preco,
                  "contexto": apresentacao, "declaracoes": declaracoes, "campos": campos}
    serializado = json.dumps(comparacao, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {"versao": 1, "chave": hashlib.sha256(serializado.encode("utf-8")).hexdigest(),
            "comparacao": comparacao}


def identificar(produto: dict, texto: str = "", contexto: dict | None = None,
                url_resolvida: str | None = None) -> dict:
    """Retorna JSON v2; chave SHA256 completa ou null, sem mutar entradas.

    ``url_resolvida`` é somente o resultado validado de enriquecimento/cache; o
    link original nunca é reescrito. Null não vira vendedor padrão/sem cupom.
    Não aplicável precisa de motivo explícito e não é aceito para loja/produto,
    vendedor, estado ou quantidade. Diagnósticos retornam códigos, não segredos.
    """
    evidencias: dict[str, list[dict[str, Any]]] = {campo: [] for campo in _CAMPOS}
    conflitos: list[str] = []
    problemas: list[str] = []

    def adicionar(campo: str, valor: Any, fonte: str) -> None:
        declaracao = _declaracao(valor, fonte)
        if declaracao is not None:
            evidencias[campo].append(declaracao)
        elif valor is not None:
            problemas.append(f"declaracao_invalida:{campo}")

    original = url_resolvida if url_resolvida is not None else produto.get("link")
    url = normalizar_url(original) if isinstance(original, str) else None
    regra, dados, erro = _formato(url) if url else (None, {}, "sem_url")
    if erro:
        problemas.append(erro)
    for campo in ("loja", "produto", "anuncio"):
        if campo in dados:
            adicionar(campo, dados[campo], "url_formato_exato")
    dados_originais: dict[str, str] = {}
    if url_resolvida is not None and isinstance(produto.get("link"), str):
        regra_original, dados_originais, erro_original = _formato(normalizar_url(produto["link"]))
        if regra_original and erro_original:
            problemas.append(f"url_original:{erro_original}")
        if "#" in produto["link"]:
            problemas.append("fragmento_original_nao_suportado")
        for campo in ("loja", "produto", "anuncio"):
            if campo in dados_originais:
                adicionar(campo, dados_originais[campo], "url_original_formato_exato")
    contexto = contexto or {}
    declaradas = contexto.get("identidade", {})
    if not isinstance(declaradas, dict):
        problemas.append("contexto_identidade_invalido")
        declaradas = {}
    for campo, valor in declaradas.items():
        if campo not in evidencias:
            problemas.append("campo_nao_suportado")
        else:
            adicionar(campo, valor, f"contexto.identidade.{campo}")
    for indice, linha in enumerate(texto.splitlines()):
        rotulo, separador, valor = linha.strip().partition(":")
        if separador and rotulo in _ROTULOS:
            adicionar(_ROTULOS[rotulo], valor, f"texto.linha:{indice + 1}")
        elif _RESTRICAO_LIVRE.search(linha):
            # Não apagar uma restrição que este parser pequeno não compreende.
            problemas.append("restricao_textual_nao_interpretada")
    cupom = produto.get("cupom")
    if cupom is not None:
        adicionar("cupom", cupom, "produto.cupom")

    campos: dict[str, dict[str, Any]] = {}
    for campo, provas in evidencias.items():
        valores = {(p["estado"], p["valor"]) for p in provas}
        if len(valores) > 1:
            conflitos.append(campo)
            campos[campo] = {"estado": "conflito", "valor": None}
        elif valores:
            estado, valor = next(iter(valores))
            campos[campo] = {"estado": estado, "valor": valor}
        else:
            campos[campo] = {"estado": "desconhecido", "valor": None}
    # smid nunca confirma sozinho o vendedor; funciona como verificação adicional.
    sellers = [d["seller_url"] for d in (dados, dados_originais) if "seller_url" in d]
    for seller in sellers:
        evidencias["vendedor"].append({"estado": "candidato", "valor": seller, "fonte": "url.smid"})
        if campos["vendedor"]["estado"] == "conhecido" and campos["vendedor"]["valor"] != seller:
            conflitos.append("vendedor")
            campos["vendedor"] = {"estado": "conflito", "valor": None}
    if len(set(sellers)) > 1:
        conflitos.append("vendedor")
        campos["vendedor"] = {"estado": "conflito", "valor": None}
    for campo in ("loja", "produto", "vendedor", "estado", "quantidade"):
        if campos[campo]["estado"] == "nao_aplicavel":
            problemas.append(f"nao_aplicavel_invalido:{campo}")
    quantidade = campos["quantidade"]
    if quantidade["estado"] == "conhecido" and not re.fullmatch(r"[1-9][0-9]{0,5}", quantidade["valor"]):
        problemas.append("quantidade_invalida")
    faltam = [campo for campo in _OBRIGATORIOS if campos[campo]["estado"] == "desconhecido"]
    comparacao = {"regra": regra, "campos": campos,
                  "url": {k: v for k, v in dados.items() if k in {
                      "origem", "path", "query", "query_vazia_explicita"}}}
    forte = regra is not None and not (problemas or conflitos or faltam)
    chave = hashlib.sha256(json.dumps(comparacao, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest() if forte else None
    motivo = "identidade_forte" if forte else (
        "campos_conflitantes" if conflitos else (problemas[0] if problemas else "evidencia_incompleta"))
    resultado = {"versao": 2, "chave": chave, "copia_versao": 1, "componentes": {
        "regra": regra, "confianca": "forte" if forte else "insuficiente", "campos": campos,
        "evidencias": evidencias, "conflitos": sorted(set(conflitos)),
        "incertezas": sorted(set(problemas)), "desconhecidos": faltam,
        "urls": {"original": normalizar_url(produto["link"]) if isinstance(produto.get("link"), str) else None,
                 "resolvida": url if url_resolvida is not None else None},
        "comparacao": comparacao,
    }, "motivo": motivo, "url_identidade": url}
    copia = _publicacao_copia(produto, texto, contexto, regra, dados, campos, conflitos, problemas)
    if copia is not None:
        resultado["copia"] = copia
    return resultado
