"""Regras locais, preparadas por snapshot e com diagnóstico sem conteúdo privado."""

import re
from dataclasses import dataclass
from typing import Any

from .dinheiro import em_centavos
from .normalizacao import normalizar_texto

CATEGORIAS = frozenset({"eletronicos", "casa", "moda", "alimentos", "beleza", "games", "outros"})


@dataclass(frozen=True)
class TermoPreparado:
    """Literal normalizado permite descartar ausência sem varrer com regex."""

    texto: str
    padrao: re.Pattern[str]


@dataclass(frozen=True)
class RegraPreparada:
    """Snapshot imutável: validação, normalização e regex fora do caminho por oferta."""

    identificador: int | str
    tipo: str
    modo: str
    categoria: str | None
    teto_centavos: int | None
    chaves: tuple[TermoPreparado, ...]
    bloqueios: tuple[TermoPreparado, ...]


@dataclass(frozen=True)
class ResultadoAvaliacao:
    """Resultado serializável sem texto, termos de filtro ou nomes privados."""

    aceita: bool
    motivo: str
    regra: int | str | None = None
    por_regra: tuple[dict, ...] = ()

    def como_dict(self) -> dict:
        return {"aceita": self.aceita, "motivo": self.motivo,
                "regra": self.regra, "por_regra": list(self.por_regra)}


def _termos(valor: Any) -> tuple[TermoPreparado, ...]:
    # NULL em arrays era permitido no schema legado e equivale a lista vazia.
    if valor is None:
        valor = []
    if not isinstance(valor, list) or len(valor) > 50:
        raise ValueError("configuracao_filtros_invalida")
    vistos: set[str] = set()
    padroes = []
    for termo in valor:
        if not isinstance(termo, str) or not 1 <= len(termo.strip()) <= 100:
            raise ValueError("configuracao_filtros_invalida")
        normalizado = normalizar_texto(termo)
        if not normalizado or normalizado in vistos:
            raise ValueError("configuracao_filtros_invalida")
        vistos.add(normalizado)
        padrao = r"(?<!\w)" + r"\s+".join(re.escape(p) for p in normalizado.split()) + r"(?!\w)"
        padroes.append(TermoPreparado(normalizado, re.compile(padrao)))
    return tuple(padroes)


def preparar_filtros(filtros: list[dict]) -> tuple[RegraPreparada, ...]:
    """Valida completamente uma resposta antes de disponibilizar o snapshot.

    Campos novos omitidos têm defaults legados. Isso não é fallback para schema
    remoto ausente: o repositório real exige as novas colunas explicitamente.
    """
    if not isinstance(filtros, list):
        raise ValueError("configuracao_filtros_invalida")
    preparadas = []
    for indice, filtro in enumerate(filtros):
        if not isinstance(filtro, dict):
            raise ValueError("configuracao_filtros_invalida")
        tipo = filtro.get("tipo_regra", "interesse")
        modo = filtro.get("modo_palavras", "qualquer")
        categoria = filtro.get("categoria")
        ativo = filtro.get("ativo", True)
        nome = filtro.get("nome")
        if (tipo not in ("interesse", "bloqueio_global") or modo not in ("qualquer", "todas")
                or not isinstance(ativo, bool)
                or (categoria is not None and (not isinstance(categoria, str) or categoria not in CATEGORIAS))
                or (nome is not None and (not isinstance(nome, str) or not 1 <= len(nome.strip()) <= 100))):
            raise ValueError("configuracao_filtros_invalida")
        chaves = _termos(filtro.get("palavras_chave"))
        bloqueios = _termos(filtro.get("palavras_bloqueio"))
        teto = filtro.get("preco_max")
        teto_centavos = em_centavos(teto) if teto is not None else None
        if tipo == "bloqueio_global" and (not bloqueios or chaves or categoria is not None or teto is not None):
            raise ValueError("configuracao_filtros_invalida")
        identificador = filtro.get("id", indice)
        if (not isinstance(identificador, (int, str)) or isinstance(identificador, bool)
                or (isinstance(identificador, str) and not re.fullmatch(r"[0-9]{1,20}", identificador))):
            raise ValueError("configuracao_filtros_invalida")
        if ativo:
            preparadas.append(RegraPreparada(identificador, tipo, modo, categoria,
                                            teto_centavos, chaves, bloqueios))
    return tuple(preparadas)


def _corresponde(texto: str, termos: tuple[TermoPreparado, ...], modo: str,
                cache: dict[TermoPreparado, bool]) -> bool:
    def bate(termo: TermoPreparado) -> bool:
        if termo not in cache:
            # Descrição e termos já têm espaços colapsados. A busca literal em
            # C evita milhares de scans regex em listas grandes sem matches;
            # regex só confirma limites de palavra de candidatos existentes.
            cache[termo] = termo.texto in texto and termo.padrao.search(texto) is not None
        return cache[termo]

    resultados = (bate(p) for p in termos)
    return all(resultados) if modo == "todas" else any(resultados)


def avaliar_produto(produto: dict, filtros: list[dict] | tuple[RegraPreparada, ...],
                    *, conteudo: str | None = None, normalizado: bool = False) -> ResultadoAvaliacao:
    """Avalia globais primeiro, depois OR entre interesses com condições em AND."""
    regras = filtros if isinstance(filtros, tuple) else preparar_filtros(filtros)
    if any(not isinstance(r, RegraPreparada) for r in regras):
        raise ValueError("configuracao_filtros_invalida")
    texto = conteudo if normalizado and conteudo is not None else normalizar_texto(
        conteudo if conteudo is not None else produto.get("titulo") or "")
    correspondencias: dict[TermoPreparado, bool] = {}
    por_regra = []
    for regra in regras:
        if regra.tipo != "bloqueio_global":
            continue
        bateu = _corresponde(texto, regra.bloqueios, regra.modo, correspondencias)
        por_regra.append({"regra": regra.identificador,
                          "motivos": ["bloqueio_global"] if bateu else ["sem_correspondencia"]})
        if bateu:
            return ResultadoAvaliacao(False, "bloqueio_global", regra.identificador, tuple(por_regra))
    interesses = [r for r in regras if r.tipo == "interesse"]
    if not interesses:
        return ResultadoAvaliacao(True, "aceita_sem_interesses", por_regra=tuple(por_regra))
    preco = produto.get("preco")
    try:
        centavos = em_centavos(preco) if preco is not None else None
    except ValueError:
        # Dado de produto inválido não invalida o snapshot inteiro.
        return ResultadoAvaliacao(False, "preco_ambiguo")
    primeira_aceita = None
    for regra in interesses:
        motivos = []
        if _corresponde(texto, regra.bloqueios, "qualquer", correspondencias):
            motivos.append("bloqueio_da_regra")
        if regra.categoria is not None and regra.categoria != produto.get("categoria"):
            motivos.append("categoria_divergente")
        if regra.teto_centavos is not None:
            if centavos is None:
                motivos.append("preco_desconhecido")
            elif centavos > regra.teto_centavos:
                motivos.append("preco_acima_do_limite")
        if regra.chaves and not _corresponde(texto, regra.chaves, regra.modo, correspondencias):
            motivos.append("palavra_ausente")
        if not motivos:
            motivos = ["aceita_por_regra"]
            if primeira_aceita is None:
                primeira_aceita = regra.identificador
        por_regra.append({"regra": regra.identificador, "motivos": motivos})
    if primeira_aceita is not None:
        return ResultadoAvaliacao(True, "aceita_por_regra", primeira_aceita, tuple(por_regra))
    return ResultadoAvaliacao(False, "nenhuma_regra_aceitou", por_regra=tuple(por_regra))


def passa_no_filtro(produto: dict, filtros: list[dict]) -> bool:
    """Compatibilidade para consumidores que só precisam do booleano."""
    return avaliar_produto(produto, filtros).aceita
