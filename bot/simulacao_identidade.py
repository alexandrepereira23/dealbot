"""Simulação offline da identidade v2, sem credenciais (executar em bot/).

    python -m simulacao_identidade --seed 42 --pares 10 --cenario todos
    python -m simulacao_identidade --seed 42 --pares 1 --cenario lento --resolucao-ms 500

O benchmark original ``python -m simulacao ...`` permanece intocado. Este modelo
usa uma espera lógica por RPC fake, não as cinco operações do benchmark legado.
Os cenários frio/quente/lento usam EXATAMENTE as mesmas entradas. Cache quente é
persistido e reaberto antes da medição; frio/lento seguram a resposta de resolução
por barreira até todas as ofertas estarem disponíveis, depois medem convergência.
Não mede nem garante latência/isolamento de VPS, Supabase ou PostgreSQL.
"""

import argparse
import asyncio
import hashlib
import json
import math
import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from cenarios_identidade import (
    AMAZON, RepositorioIdentidadeFake, ResolvedorFake, StorageFake, TelegramFake,
    aguardar, linhas, mensagem_sintetica,
)
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.pipeline_identidade import PipelineIdentidade


CENARIOS = ("fortes", "frio", "quente", "lento")


@dataclass(frozen=True)
class Parametros:
    seed: int = 42
    pares: int = 10
    cenario: str = "todos"
    db_ms: float = 20
    resolucao_ms: float = 200
    oferta_workers: int = 4
    enriquecimento_workers: int = 1
    prazo: float = 120

    def __post_init__(self):
        for nome in ("pares", "oferta_workers", "enriquecimento_workers"):
            if type(getattr(self, nome)) is not int or getattr(self, nome) <= 0:
                raise ValueError(f"{nome} deve ser inteiro positivo")
        if self.cenario not in (*CENARIOS, "todos"):
            raise ValueError("cenario desconhecido")
        for nome in ("db_ms", "resolucao_ms", "prazo"):
            if not math.isfinite(getattr(self, nome)) or getattr(self, nome) < 0:
                raise ValueError(f"{nome} deve ser finito e não negativo")
        if self.prazo == 0:
            raise ValueError("prazo deve ser positivo")
        if self.enriquecimento_workers > 8:
            raise ValueError("enriquecimento_workers deve ser no máximo 8")


def dataset(parametros, cenario):
    """Gerador limitado; digest não inclui relógio/latência nem nome do cenário."""
    rng = random.Random(parametros.seed)
    for indice in range(parametros.pares):
        asin = f"B{indice:09d}"
        destino = AMAZON.replace("B012345678", asin)
        token = f"{rng.getrandbits(64):016X}"
        for canal, host, sufixo in ((-100111, "amzn.to", "AbC"), (-100222, "meli.la", "XyZ")):
            url = (destino + f"?tag=canal{abs(canal)}-20" if cenario == "fortes"
                   else f"https://{host}/{token}{sufixo}")
            yield mensagem_sintetica(indice + 1, canal, url=url, foto=True,
                                     origem="live" if canal == -100111 else "historico"), destino


def resumir(valores):
    ordenadas = sorted(valores)
    def percentil(p):
        return round(ordenadas[max(0, math.ceil(len(ordenadas) * p) - 1)], 3) if ordenadas else None
    return {"quantidade": len(valores), "p50": percentil(.5), "p95": percentil(.95), "max": percentil(1)}


async def fotografia(estado, repo):
    ofertas = (await estado.resumo())["ofertas"]
    enriquecimentos = await linhas(estado, "SELECT estado,COUNT(*) AS n FROM enriquecimentos GROUP BY estado")
    midias = await linhas(estado, "SELECT COUNT(*) AS n FROM midias WHERE finalizado_em IS NULL OR compensar=1")
    acks = await linhas(estado, "SELECT COUNT(*) AS n FROM eventos WHERE identidade IS NOT NULL AND remoto_confirmado=0")
    return {
        "cards_ativos_fake": len(repo.ativos), "aparicoes_fake": len(repo.aparicoes),
        "observacoes_fake": len(repo.observacoes), "aliases_fake": len(repo.aliases),
        "ofertas": ofertas, "enriquecimentos": {r["estado"]: r["n"] for r in enriquecimentos},
        "pendencias": {
            "ofertas": sum(n for e, n in ofertas.items() if e not in ("aprovada", "duplicata", "descartada", "falha_permanente")),
            "midia": midias[0]["n"], "ack": acks[0]["n"],
            "enriquecimento": sum(r["n"] for r in enriquecimentos if r["estado"] not in ("concluido", "esgotado")),
        },
    }


async def executar_cenario(parametros, cenario):
    base = Path(tempfile.gettempdir()) / "opencode"
    with tempfile.TemporaryDirectory(prefix="dealbot-identidade-", dir=base if base.is_dir() else None) as temporario:
        config = Config(state_dir=Path(temporario), oferta_workers=parametros.oferta_workers,
                        enriquecimento_workers=parametros.enriquecimento_workers,
                        retry_base=.02, retry_max=.05, shutdown_timeout=.05,
                        resolucao_timeout=max(5, parametros.resolucao_ms / 1000 + parametros.prazo + 1))
        estado = EstadoLocal(config.state_dir)
        repo = RepositorioIdentidadeFake(atraso=parametros.db_ms / 1000)
        # O mapa de destinos é do fixture fake, não cache/transporte de produção.
        destinos = {m.texto.splitlines()[-1]: destino for m, destino in dataset(parametros, cenario)}
        resolvedor = ResolvedorFake(destinos, bloqueado=cenario in ("frio", "lento"),
                                   atraso=parametros.resolucao_ms / 1000 if cenario == "lento" else 0)
        cache = CacheFiltros(repo)
        await estado.abrir()
        pipeline = None
        batida = None
        parar = asyncio.Event()
        heartbeat_max = 0
        try:
            if cenario == "quente":
                for url, destino in destinos.items():
                    await estado.guardar_cache_url(url,
                        {"estado": "positivo", "url_final": destino, "motivo": "fixture_cache", "versao": 2},
                        time.time() + config.resolucao_cache_positivo)
                await estado.fechar()
                estado = EstadoLocal(config.state_dir)
                await estado.abrir()  # Prova de cache após restart, fora da janela medida.
            await cache.atualizar()
            pipeline = PipelineIdentidade(estado, repo, StorageFake(), TelegramFake(), cache, config,
                                          resolvedor=resolvedor)

            async def heartbeat():
                nonlocal heartbeat_max
                while not parar.is_set():
                    inicio = time.monotonic()
                    await asyncio.sleep(.01)
                    heartbeat_max = max(heartbeat_max, time.monotonic() - inicio - .01)

            async def ofertas_terminadas():
                resumo = (await estado.resumo())["ofertas"]
                return sum(resumo.get(e, 0) for e in ("aprovada", "duplicata")) == parametros.pares * 2

            async def sem_pendencias():
                return not any((await fotografia(estado, repo))["pendencias"].values())

            digest = hashlib.sha256()
            inicio = time.monotonic()
            pipeline.iniciar()
            batida = asyncio.create_task(heartbeat(), name="identidade-heartbeat")
            for mensagem, _ in dataset(parametros, cenario):
                digest.update(json.dumps({"canal": mensagem.canal_id, "msg": mensagem.msg_id,
                    "texto": mensagem.texto, "contexto": mensagem.contexto, "origem": mensagem.origem},
                    sort_keys=True, ensure_ascii=True).encode())
                await pipeline.receber(mensagem)
            await aguardar(ofertas_terminadas, timeout=parametros.prazo, pipeline=pipeline)
            fim_ofertas = time.monotonic()
            antes = await fotografia(estado, repo)
            eventos = await linhas(estado, "SELECT origem,recebido_em,disponibilizado_em,identidade FROM eventos")
            latencias = {origem: resumir([(e["disponibilizado_em"] - e["recebido_em"]) * 1000
                                        for e in eventos if e["origem"] == origem])
                         for origem in ("live", "historico")}
            cache_hits = sum(bool(json.loads(e["identidade"])["chave"]) for e in eventos) if cenario == "quente" else 0
            barreira = None
            if cenario in ("frio", "lento"):
                await asyncio.wait_for(resolvedor.iniciou.wait(), parametros.prazo)
                barreira = {"ofertas_salvas_antes_de_liberar": len(repo.aparicoes),
                            "resolucao_ativa": resolvedor.ativos,
                            "resposta_ainda_bloqueada": not resolvedor.liberar.is_set()}
                if len(repo.aparicoes) != parametros.pares * 2 or resolvedor.liberar.is_set():
                    raise AssertionError("A barreira não comprovou oferta antes da resolução")
            liberacao = time.monotonic()
            resolvedor.liberar.set()
            await aguardar(sem_pendencias, timeout=parametros.prazo, pipeline=pipeline)
            fim_convergencia = time.monotonic()
            depois = await fotografia(estado, repo)
            if depois["cards_ativos_fake"] != parametros.pares or depois["aparicoes_fake"] != parametros.pares * 2:
                raise AssertionError("Fixtures fortes não convergiram no repositório fake")
            return {
                "cenario": cenario, "dataset_sha256": digest.hexdigest(),
                "latencia_oferta_ms": latencias,
                "janela_ofertas_s": round(fim_ofertas - inicio, 6),
                "convergencia_apos_liberacao_s": round(fim_convergencia - liberacao, 6),
                "vazao_ofertas_s": round(parametros.pares * 2 / (fim_ofertas - inicio), 3),
                "antes_liberar_resolucao": antes, "apos_convergencia": depois,
                "barreira": barreira, "cache_hits_caminho_oferta": cache_hits,
                "resolucoes_fake": len(resolvedor.chamadas),
                "heartbeat_atraso_max_ms": round(heartbeat_max * 1000, 3),
                "workers": {"configurados": {"oferta": config.oferta_workers, "midia": config.midia_workers,
                                               "enriquecimento": config.enriquecimento_workers},
                            "max_ativos": dict(pipeline.max_ativos), "max_rede_fake": resolvedor.max_ativos},
                "rpc_fake_chamadas": dict(repo.chamadas),
            }
        finally:
            parar.set()
            if batida:
                await batida
            if pipeline:
                await pipeline.encerrar()
            await estado.fechar()


async def executar(parametros):
    cenarios = CENARIOS if parametros.cenario == "todos" else (parametros.cenario,)
    resultados = [await executar_cenario(parametros, cenario) for cenario in cenarios]
    digests = {r["dataset_sha256"] for r in resultados if r["cenario"] in ("frio", "quente", "lento")}
    if len(digests) > 1:
        raise AssertionError("Comparação de cache usou datasets diferentes")
    return {"parametros": vars(parametros), "resultados": resultados, "avisos": [
        "SQLite real temporário WAL/FULL; identidades reais; DNS/HTTP/Telegram/Storage/Postgres exclusivamente falsos.",
        "Modelo RPC: uma espera lógica por operação. Não compara roundtrips diretamente com simulacao.py (cinco operações legadas).",
        "Latência: recebimento até vínculo SQLite após RPC fake de oferta/aparição; não inclui convergência, setup ou shutdown.",
        "Frio/lento seguram respostas por barreira artificial até TODAS as ofertas salvas; não são tráfego ou SLA reais.",
        "Quente reabre SQLite com cache válido pré-semeado; a preparação do cache não é medida.",
        "Fake de cards não prova transação, expiração ou atualização de preços: exigem testes SQL separados.",
        "Seed fixa entradas, não escalonamento. Dados fake/destinos/amostras crescem com a carga; sem task por mensagem.",
        "Não é garantia de latência VPS/Supabase/Postgres; conserva benchmark legado em comando separado.",
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cenario", choices=(*CENARIOS, "todos"), default="todos")
    for nome, padrao, tipo in (("seed", 42, int), ("pares", 10, int), ("db-ms", 20, float),
                               ("resolucao-ms", 200, float), ("oferta-workers", 4, int),
                               ("enriquecimento-workers", 1, int), ("prazo", 120, float)):
        parser.add_argument("--" + nome, default=padrao, type=tipo)
    try:
        parametros = Parametros(**vars(parser.parse_args()))
    except ValueError as erro:
        parser.error(str(erro))
    print(json.dumps(asyncio.run(executar(parametros)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
