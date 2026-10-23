"""Benchmark offline: ``python -m simulacao --seed 42`` (a partir de bot/).

SQLite real, rede exclusivamente simulada e produtores de memória limitada.
As amostras de latência são resultados do benchmark, não uma fila em memória.
"""

import argparse
import asyncio
import hashlib
import json
import math
import random
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal, MIDIA_TERMINAIS, TERMINAIS
from src.modelos import Aguardar, Mensagem
from src.pipeline import Pipeline
from src.repository import ResultadoOferta


@dataclass(frozen=True)
class Parametros:
    seed: int = 42
    live: int = 100
    historico: int = 1000
    db_ms: float = 100
    midia_ms: float = 2000
    oferta_workers: int = 4
    midia_workers: int = 1
    midia_falha: bool = False

    def __post_init__(self) -> None:
        for nome in ("live", "historico", "oferta_workers", "midia_workers"):
            valor = getattr(self, nome)
            if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
                raise ValueError(f"{nome} precisa ser um inteiro não negativo")
        if not self.live + self.historico or not self.oferta_workers or not self.midia_workers:
            raise ValueError("Informe eventos e pelo menos um worker de cada classe")
        for nome in ("db_ms", "midia_ms"):
            if not math.isfinite(getattr(self, nome)) or getattr(self, nome) < 0:
                raise ValueError(f"{nome} precisa ser não negativo e finito")


@dataclass(frozen=True)
class EntradaSimulada(Mensagem):
    recebido_monotonico: float = field(default_factory=time.monotonic)


class EstadoMedido(EstadoLocal):
    """Instrumentação local, no MESMO executor serial do SQLite.

    O hook privado só observa operações: não muda seleção, claims ou commits.
    Agregação após cada operação evita perder picos entre duas amostragens.
    O backend falso também fica em disco, não em dicionários por mensagem.
    """

    def __init__(self, config: Config, total: int) -> None:
        super().__init__(config.state_dir, config.buffer_max, config.prioridade_live_cota)
        self.total = total
        self.medindo = False
        self.fim_ofertas: float | None = None
        self.filas = {classe: {"inicial": 0, "pico": 0, "final": 0}
                      for classe in ("live", "historico", "midia")}
        self.contagens: dict[str, Any] = {}

    def _abrir(self) -> None:
        super()._abrir()
        self._conexao().executescript("""
            CREATE TABLE benchmark_recebimentos (
                canal_id INTEGER, msg_id INTEGER, monotono REAL,
                PRIMARY KEY(canal_id,msg_id));
            CREATE TABLE benchmark_produtos (
                id INTEGER PRIMARY KEY, canal TEXT, msg_id INTEGER,
                foto_url TEXT, aparicao INTEGER NOT NULL DEFAULT 0,
                UNIQUE(canal,msg_id));
        """)

    def _inserir(self, msg: Mensagem) -> bool:
        novo = super()._inserir(msg)
        if novo:
            self._conexao().execute("INSERT INTO benchmark_recebimentos VALUES(?,?,?)",
                (msg.canal_id, msg.msg_id, msg.recebido_monotonico))
        return novo

    async def _executar(self, fn: Any, *args: Any) -> Any:
        def observar() -> Any:
            resultado = fn(*args)
            if self.medindo and self.db is not None:
                grupos = list(self.db.execute(
                    "SELECT origem,estado,COUNT(*) FROM eventos GROUP BY origem,estado"))
                midias = list(self.db.execute(
                    "SELECT estado,compensar,COUNT(*) FROM midias GROUP BY estado,compensar"))
                ofertas = Counter()
                por_origem = {"live": Counter(), "historico": Counter()}
                pendentes = Counter()
                for origem, estado, quantidade in grupos:
                    ofertas[estado] += quantidade
                    por_origem[origem][estado] += quantidade
                    if estado not in TERMINAIS:
                        pendentes[origem] += quantidade
                pendentes["midia"] = sum(n for estado, compensar, n in midias
                                          if estado not in MIDIA_TERMINAIS or compensar)
                for classe, fila in self.filas.items():
                    fila["pico"] = max(fila["pico"], pendentes[classe])
                    fila["final"] = pendentes[classe]
                contagem_midias: Counter = Counter()
                for estado, _, quantidade in midias:
                    contagem_midias[estado] += quantidade
                self.contagens = {"ofertas": dict(ofertas), "por_origem": por_origem,
                                  "midias": dict(contagem_midias)}
                if sum(ofertas[e] for e in TERMINAIS) == self.total:
                    self.fim_ofertas = time.monotonic()
                    self.medindo = False
            return resultado
        return await super()._executar(observar)

    async def sql(self, consulta: str, valores: tuple = ()) -> list[tuple]:
        def executar() -> list[tuple]:
            with self._conexao():
                return [tuple(r) for r in self._conexao().execute(consulta, valores)]
        return await self._executar(executar)


class RepositorioSimulado:
    # Dataset distinto: caminho feliz de novo produto. Não equivale a executar SDK.
    OPERACOES = ("reconciliar_produto", "reconciliar_aparicao", "buscar_hash",
                 "inserir_produto", "registrar_aparicao")

    def __init__(self, estado: EstadoMedido, parametros: Parametros) -> None:
        self.estado = estado
        self.parametros = parametros
        self.operacoes: Counter = Counter()
        self.latencias: dict[str, list[float]] = {"live": [], "historico": []}
        self.primeiro: dict[str, float] = {}
        self.ultimo: dict[str, float] = {}

    async def _rede(self, operacao: str) -> None:
        self.operacoes[operacao] += 1
        await asyncio.sleep(self.parametros.db_ms / 1000)

    async def carregar_filtros(self) -> list[dict]:
        await self._rede("carregar_filtros")
        return []

    async def listar_canais(self) -> list[str]:
        await self._rede("listar_canais")
        return ["sim_live", "sim_historico"]

    async def salvar_oferta(self, registro: dict, aliases: list[str],
                            produto_id: int | None = None, ao_vincular: Any = None) -> ResultadoOferta:
        for operacao in self.OPERACOES[:4]:
            await self._rede(operacao)
        # As cinco esperas modelam operações lógicas; não há Supabase/SDK aqui.
        await self.estado.sql("INSERT OR IGNORE INTO benchmark_produtos(canal,msg_id) VALUES(?,?)",
                              (registro["canal_origem"], registro["telegram_msg_id"]))
        linha = (await self.estado.sql(
            "SELECT id,foto_url FROM benchmark_produtos WHERE canal=? AND msg_id=?",
            (registro["canal_origem"], registro["telegram_msg_id"])))[0]
        produto_id, foto = linha
        # Disponibilidade da oferta independe do registro posterior da aparição.
        confirmado = time.monotonic()
        if ao_vincular is not None:
            await ao_vincular(produto_id)
        await self._rede(self.OPERACOES[4])
        await self.estado.sql("UPDATE benchmark_produtos SET aparicao=1 WHERE id=?", (produto_id,))
        origem = "live" if registro["canal_origem"] == "sim_live" else "historico"
        canal_id = -1001 if origem == "live" else -1002
        recebido = (await self.estado.sql(
            "SELECT monotono FROM benchmark_recebimentos WHERE canal_id=? AND msg_id=?",
            (canal_id, registro["telegram_msg_id"])))[0][0]
        self.latencias[origem].append((confirmado - recebido) * 1000)
        self.primeiro.setdefault(origem, confirmado)
        self.ultimo[origem] = confirmado
        return ResultadoOferta(produto_id, "novo", foto)

    async def buscar_produto(self, produto_id: int) -> dict | None:
        await self._rede("buscar_produto_midia")
        linhas = await self.estado.sql("SELECT id,foto_url FROM benchmark_produtos WHERE id=?", (produto_id,))
        return {"id": linhas[0][0], "foto_url": linhas[0][1]} if linhas else None

    async def vincular_foto(self, produto_id: int, url: str) -> str:
        await self._rede("vincular_foto")
        await self.estado.sql("UPDATE benchmark_produtos SET foto_url=COALESCE(foto_url,?) WHERE id=?",
                              (url, produto_id))
        return "atualizada"


class TelegramSimulado:
    def __init__(self, parametros: Parametros) -> None:
        self.parametros = parametros
        self.chamadas = 0
        self.falhas = 0

    async def baixar_foto(self, canal_id: int, msg_id: int, limite: int) -> bytes:
        self.chamadas += 1
        # midia-ms é o delay TOTAL download+upload (metade em cada etapa).
        await asyncio.sleep(self.parametros.midia_ms / 2000)
        if self.parametros.midia_falha:
            self.falhas += 1
            raise Aguardar(3600, "midia_fake_indisponivel")
        return b"foto-simulada"[:limite]


class ArmazenamentoSimulado:
    def __init__(self, parametros: Parametros) -> None:
        self.parametros = parametros

    async def enviar(self, chave: str, dados: bytes) -> str:
        await asyncio.sleep(self.parametros.midia_ms / 2000)
        return "https://storage.invalid/" + chave

    async def remover(self, chave: str) -> None:
        await asyncio.sleep(0)


def resumir_latencias(valores: list[float]) -> dict:
    ordenadas = sorted(valores)
    def percentil(p: float) -> float | None:
        return round(ordenadas[max(0, math.ceil(len(ordenadas) * p) - 1)], 3) if ordenadas else None
    return {"quantidade": len(valores), "p50": percentil(.50), "p95": percentil(.95),
            "max": percentil(1)}


async def executar(parametros: Parametros) -> dict:
    """Finaliza a medição após ofertas terminais; NÃO drena o backlog de fotos."""
    base_temporaria = Path(tempfile.gettempdir()) / "opencode"
    with tempfile.TemporaryDirectory(prefix="dealbot-simulacao-",
                                     dir=base_temporaria if base_temporaria.is_dir() else None) as temporario:
        config = Config(state_dir=Path(temporario), oferta_workers=parametros.oferta_workers,
                        midia_workers=parametros.midia_workers, buffer_max=100, recuperacao_lote=100,
                        shutdown_timeout=.01, midia_timeout=max(30, parametros.midia_ms / 1000 + 10))
        estado = EstadoMedido(config, parametros.live + parametros.historico)
        repositorio = RepositorioSimulado(estado, parametros)
        telegram = TelegramSimulado(parametros)
        cache = CacheFiltros(repositorio, timeout=max(10, parametros.db_ms / 1000 + 5))
        pipeline = Pipeline(estado, repositorio, ArmazenamentoSimulado(parametros), telegram, cache, config)
        tarefas: list[asyncio.Task] = []
        parar = asyncio.Event()
        atraso_max = 0.0
        pagina_max = 0
        digests: dict[str, str] = {}
        await estado.abrir()
        try:
            await cache.atualizar()
            for canal_id, nome in ((-1001, "sim_live"), (-1002, "sim_historico")):
                await estado.configurar_canal(canal_id, nome, None, time.time() - 86400)

            async def heartbeat() -> None:
                nonlocal atraso_max
                while not parar.is_set():
                    previsto = time.monotonic() + .01
                    await asyncio.sleep(.01)
                    atraso_max = max(atraso_max, time.monotonic() - previsto)

            async def produzir(origem: str, quantidade: int) -> None:
                nonlocal pagina_max
                # RNG separado por classe: interleaving do SO não muda o dataset.
                rng = random.Random(f"{parametros.seed}:{origem}")
                digest = hashlib.sha256()
                pagina: list[EntradaSimulada] = []
                canal_id = -1001 if origem == "live" else -1002
                inicio_produtor = time.monotonic()
                for indice in range(quantidade):
                    if origem == "live" and indice:
                        await asyncio.sleep(max(0, inicio_produtor + indice * .05 - time.monotonic()))
                    texto = (f"Notebook simulado {origem} {indice:08d}\n"
                             f"R$ {rng.randrange(100, 10000)},90\n"
                             f"https://oferta.invalid/{origem}/{indice}")
                    digest.update(texto.encode())
                    # Idade Telegram é artificial e não entra na latência local.
                    data = (datetime.now(timezone.utc)
                            - timedelta(hours=12 if origem == "historico" else 0)).isoformat()
                    msg = EntradaSimulada(canal_id, indice * 3 + 1, f"sim_{origem}", texto,
                                          data, tem_foto=True, origem=origem)
                    if origem == "live":
                        await pipeline.receber(msg)
                    else:
                        pagina.append(msg)
                        pagina_max = max(pagina_max, len(pagina))
                        if len(pagina) == config.recuperacao_lote or indice == quantidade - 1:
                            await estado.registrar_pagina(canal_id, pagina, msg.msg_id,
                                                         indice == quantidade - 1, 0)
                            pipeline.acordar_ofertas.set()
                            pagina.clear()
                            await asyncio.sleep(0)
                digests[origem] = digest.hexdigest()

            inicio_utc = datetime.now(timezone.utc).isoformat()
            inicio = time.monotonic()
            estado.medindo = True
            pipeline.iniciar()
            tarefas = [asyncio.create_task(heartbeat(), name="sim-heartbeat"),
                       asyncio.create_task(produzir("live", parametros.live), name="sim-live"),
                       asyncio.create_task(produzir("historico", parametros.historico), name="sim-historico")]
            # Watchdog derivado da carga, apenas para tornar falhas de teste finitas.
            # fsync FULL em volumes Windows/WSL pode dominar o caso de rede zero.
            # Watchdog é segurança contra deadlock, não uma meta de desempenho.
            prazo = inicio + max(120, parametros.live * .05 +
                                (parametros.live + parametros.historico) * (5 * parametros.db_ms / 1000 + .5) * 4)
            while estado.fim_ofertas is None:
                if pipeline.fatal is not None and pipeline.fatal.done():
                    raise pipeline.fatal.result()
                for tarefa in tarefas:
                    if tarefa.done() and not tarefa.cancelled() and tarefa.exception() is not None:
                        raise tarefa.exception()
                if time.monotonic() > prazo:
                    raise TimeoutError("Simulação não finalizou as ofertas no prazo de segurança")
                await asyncio.sleep(.01)
            fim = estado.fim_ofertas
            parar.set()
            await asyncio.gather(*tarefas)
            duracao = fim - inicio
            contagens = estado.contagens
            registros = (await estado.sql("SELECT COUNT(*) FROM benchmark_produtos"))[0][0]
            sobreposicao = {origem: (repositorio.primeiro[origem] < repositorio.ultimo[outra]
                                    if origem in repositorio.primeiro and outra in repositorio.ultimo else None)
                            for origem, outra in (("live", "historico"), ("historico", "live"))}
            return {
                "parametros": vars(parametros), "dataset_sha256": digests,
                "latencia_recebimento_commit_ms": {o: resumir_latencias(v) for o, v in repositorio.latencias.items()},
                "janela_medida": {"inicio_utc": inicio_utc, "inicio_monotonico_s": inicio,
                                  "fim_monotonico_s": fim, "duracao_s": duracao,
                                  "inicio": "antes dos produtores", "fim": "última oferta terminal no SQLite",
                                  "inclui_shutdown": False},
                "vazao_ofertas_s": sum(len(v) for v in repositorio.latencias.values()) / duracao,
                "workers": {"configurados": {"oferta": config.oferta_workers, "midia": config.midia_workers},
                            "max_ativos": dict(pipeline.max_ativos)},
                "filas": estado.filas, "heartbeat_atraso_max_ms": atraso_max * 1000,
                "contagens": {"recebidas": parametros.live + parametros.historico,
                              "produtos": registros, **contagens,
                              "aprovadas": contagens["ofertas"].get("aprovada", 0),
                              "descartadas": contagens["ofertas"].get("descartada", 0),
                              "duplicadas": contagens["ofertas"].get("duplicata", 0),
                              "falhas": contagens["ofertas"].get("falha_permanente", 0),
                              "midia_tentativas": telegram.chamadas, "midia_falhas": telegram.falhas},
                "idade_origem_simulada_s": {"live": 0, "historico": 43200},
                "intervalo_live_planejado_ms": 50,
                "progresso_antes_fim_outra_classe": sobreposicao,
                "banco_simulado": {"operacoes_por_oferta_nova": 5,
                                   "operacoes": list(repositorio.OPERACOES),
                                   "delay_por_operacao_ms": parametros.db_ms,
                                   "chamadas_iniciadas": dict(repositorio.operacoes)},
                "limites_memoria": {"buffer_max": config.buffer_max, "pagina_max_observada": pagina_max,
                                    "produtores": 2, "tasks_por_mensagem": 0,
                                    "amostras_latencia": sum(len(v) for v in repositorio.latencias.values()),
                                    "resultado_benchmark_proporcional_cenario": True},
                "avisos": ["Rede fake: não valida Supabase SDK, Telegram, VPS, produção ou frontend.",
                           "Cinco operações lógicas por oferta distinta; não reproduz queries por alias, retries ou dedup real.",
                           "Filas incluem em processamento; picos observados em cada operação SQLite.",
                            "Latência termina na confirmação do produto, antes da aparição/foto; janela de vazão termina nas ofertas finalizadas. Setup e shutdown fora da janela.",
                           "midia-ms é download+upload; --midia-falha falha todos os downloads, com retry de 3600s.",
                           "Idade Telegram artificial: 12h histórico/0h live; transporte Telegram não simulado.",
                           "Amostras de latência crescem com cenário; mensagens/backend falso ficam no SQLite temporário, removido ao sair.",
                           "Instrumentação SQLite adiciona custo local; seed reproduz entradas/falhas, não tempos do escalonador."],
            }
        finally:
            parar.set()
            for tarefa in tarefas:
                if not tarefa.done():
                    tarefa.cancel()
            await asyncio.gather(*tarefas, return_exceptions=True)
            try:
                await pipeline.encerrar()
            finally:
                await estado.fechar()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for nome, padrao, tipo in (("seed", 42, int), ("live", 100, int), ("historico", 1000, int),
                              ("db-ms", 100, float), ("midia-ms", 2000, float),
                              ("oferta-workers", 4, int), ("midia-workers", 1, int)):
        parser.add_argument("--" + nome, default=padrao, type=tipo)
    parser.add_argument("--midia-falha", action="store_true")
    try:
        parametros = Parametros(**vars(parser.parse_args()))
    except ValueError as erro:
        parser.error(str(erro))
    print(json.dumps(asyncio.run(executar(parametros)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
