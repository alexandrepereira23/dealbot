"""Medição offline do corpus sintético, sempre usando os módulos de produção."""

import argparse
import asyncio
import hashlib
import json
import platform
import random
import statistics
import time
from pathlib import Path

from src import extractor, filters


def carregar_corpus() -> tuple[dict, str]:
    bruto = (Path(__file__).parent / "tests/fixtures/extracao_sintetica.json").read_bytes()
    corpus = json.loads(bruto)
    for caso in corpus["casos"]:
        caso["texto"] += caso.get("repetir", "") * caso.get("vezes", 0)
    return corpus, hashlib.sha256(bruto).hexdigest()


def resumo(amostras: list[float]) -> dict:
    ordenadas = sorted(amostras)
    return {"amostras": len(amostras), "p50_us": round(statistics.median(amostras), 3),
            "p95_us": round(ordenadas[int((len(ordenadas) - 1) * .95)], 3),
            "max_us": round(max(amostras), 3)}


async def medir(iteracoes: int) -> dict:
    corpus, digest = carregar_corpus()
    detalhado = getattr(extractor, "extrair_detalhado", None)
    preparar = getattr(filters, "preparar_filtros", None)
    avaliar = getattr(filters, "avaliar_produto", None)
    # O ID textual da fixture não é ID persistido: índice sintético é o contrato
    # novo. Não se altera o corpus congelado nem os termos/categoria/teto medidos.
    regras = [{**f, "id": i} for i, f in enumerate(corpus["filtros"])]
    preparacao = []
    if preparar:
        for _ in range(iteracoes):
            inicio = time.perf_counter_ns()
            snapshot = preparar(regras)
            preparacao.append((time.perf_counter_ns() - inicio) / 1000)
    else:
        snapshot = regras

    async def extrair(caso: dict) -> tuple[dict | None, str | None, tuple[str, ...]]:
        if detalhado:
            resultado = detalhado(caso["texto"], caso.get("contexto"))
            return resultado.produto, resultado.conteudo, resultado.motivos
        return await extractor.extrair_produto(caso["texto"]), None, ()

    exemplos = []
    for caso in corpus["casos"]:
        produto, _, motivos = await extrair(caso)
        exemplos.append({"id": caso["id"], "produto": produto, "motivos": motivos})
    for _ in range(3):
        for caso in corpus["casos"]:
            await extrair(caso)
    rng = random.Random(corpus["seed"])
    extracao, conjunto, avaliacao = [], [], []
    por_caso = {caso["id"]: [] for caso in corpus["casos"]}
    inicio_total = time.perf_counter_ns()
    for _ in range(iteracoes):
        ordem = list(corpus["casos"])
        rng.shuffle(ordem)
        for caso in ordem:
            inicio = time.perf_counter_ns()
            produto, conteudo, _ = await extrair(caso)
            fim = time.perf_counter_ns()
            if produto:
                if avaliar:
                    avaliar(produto, snapshot, conteudo=conteudo, normalizado=True)
                else:
                    filters.passa_no_filtro(produto, regras)
                avaliacao.append((time.perf_counter_ns() - fim) / 1000)
            extracao.append((fim - inicio) / 1000)
            por_caso[caso["id"]].append((fim - inicio) / 1000)
            conjunto.append((time.perf_counter_ns() - inicio) / 1000)
    duracao = (time.perf_counter_ns() - inicio_total) / 1e9
    return {"origem": corpus["origem"], "interface": "detalhada" if detalhado else "legada",
            "python": platform.python_version(), "plataforma": platform.platform(),
            "seed": corpus["seed"], "corpus_sha256": digest, "casos": len(corpus["casos"]),
            "iteracoes": iteracoes, "aquecimentos": 3, "extracao": resumo(extracao),
            "extracao_avaliacao": resumo(conjunto),
            "avaliacao_ofertas_validas": resumo(avaliacao) if avaliacao else None,
            "preparacao_snapshot": resumo(preparacao) if preparacao else None,
            "extracao_por_caso": {k: resumo(v) for k, v in por_caso.items()},
            "duracao_s": round(duracao, 6),
             "mensagens_s": round(len(extracao) / duracao, 2), "exemplos": exemplos}


def medir_limites(iteracoes: int = 20) -> dict:
    """Carga adicional de regras no limite, separada da comparação de corpus."""
    # Dez interesses, cada um com 50 inclusões e 50 bloqueios de 100 caracteres.
    # Termos distintos entre regras evitam favorecer o cache de correspondência.
    regras = [{"id": r, "palavras_chave": [(f"incluir_{r}_{t}_").ljust(100, "x") for t in range(50)],
               "palavras_bloqueio": [(f"bloquear_{r}_{t}_").ljust(100, "x") for t in range(50)]}
              for r in range(10)]
    inicio = time.perf_counter_ns()
    snapshot = filters.preparar_filtros(regras)
    preparo = (time.perf_counter_ns() - inicio) / 1000
    corpus, _ = carregar_corpus()
    amostras = {}
    for caso in corpus["casos"]:
        if caso["id"] not in {"curto", "longo", "adversarial"}:
            continue
        resultado = extractor.extrair_detalhado(caso["texto"], caso.get("contexto"))
        tempos = []
        for _ in range(iteracoes):
            inicio = time.perf_counter_ns()
            filters.avaliar_produto(resultado.produto, snapshot, conteudo=resultado.conteudo, normalizado=True)
            tempos.append((time.perf_counter_ns() - inicio) / 1000)
        amostras[caso["id"]] = {"caracteres_descritivos": len(resultado.conteudo), **resumo(tempos)}
    return {"regras": 10, "termos_por_lista": 50, "caracteres_por_termo": 100,
            "preparo_us": round(preparo, 3), "avaliacao_sem_reextrair": amostras}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iteracoes", type=int, default=100)
    parser.add_argument("--limites", action="store_true", help="Mede também regras/listas no limite, sem comparação legada")
    args = parser.parse_args()
    if args.iteracoes < 1:
        parser.error("iterações devem ser positivas")
    resultado = asyncio.run(medir(args.iteracoes))
    if args.limites:
        resultado["limites_regras"] = medir_limites()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
