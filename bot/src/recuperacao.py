"""Atualização de canais e cobertura histórica independente de mensagens live."""

import asyncio
import time
from typing import Any

from .config import Config
from .estado import EstadoLocal
from .modelos import FalhaLocal, normalizar_username
from .observabilidade import log
from .politica import classificar
from .telegram import PaginaHistorico


class Recuperacao:
    def __init__(self, estado: EstadoLocal, repositorio: Any, telegram: Any,
                 config: Config, acordar_ofertas: asyncio.Event) -> None:
        self.estado = estado
        self.repositorio = repositorio
        self.telegram = telegram
        self.config = config
        self.acordar_ofertas = acordar_ofertas
        self.acordar = asyncio.Event()
        self.ativos: dict[int, str] = {}
        self._ids_por_nome: dict[str, int] = {}
        self._refresh_lock = asyncio.Lock()
        self._rodada_lock = asyncio.Lock()

    async def atualizar_canais(self) -> None:
        """Falha global preserva lista anterior; erro de um endereço é isolado."""
        async with self._refresh_lock:
            nomes = await asyncio.wait_for(self.repositorio.listar_canais(), self.config.rede_timeout)
            if not isinstance(nomes, list) or any(not isinstance(n, str) for n in nomes):
                raise ValueError("resposta_canais_invalida")
            solicitados = {normalizar_username(n) for n in nomes if n.strip()}
            novos = {}
            registros = await self.estado.canais()
            aliases_ids = {}
            import json
            for canal in registros:
                for alias in json.loads(canal["aliases"]):
                    aliases_ids[normalizar_username(alias)] = canal["canal_id"]
            indisponiveis = 0
            for nome in sorted(solicitados):
                esperado = self._ids_por_nome.get(nome, aliases_ids.get(nome))
                # Preservar vínculos conhecidos, inclusive após reinício ou se
                # vários aliases configurados apontam para o mesmo ID estável.
                if esperado is not None:
                    novos[esperado] = nome
                retry = await self.estado.resolucao(nome)
                tentativas = retry["tentativas"] if retry else 0
                if retry and retry["proxima"] > time.time():
                    indisponiveis += 1
                    continue
                try:
                    canal = await self.telegram.resolver(nome)
                    if esperado is not None and esperado != canal["canal_id"]:
                        raise ValueError("username_reassociado_a_outro_canal")
                    self._ids_por_nome[nome] = canal["canal_id"]
                    await self.estado.configurar_canal(canal["canal_id"], nome,
                        canal.get("access_hash"), time.time() - self.config.bootstrap_horas * 3600,
                        aliases_extras=[canal["username"], *[n.strip() for n in nomes if normalizar_username(n) == nome]],
                        ativar=False)
                    novos[canal["canal_id"]] = nome
                    await self.estado.concluir_resolucao(nome)
                except FalhaLocal:
                    raise
                except Exception as erro:
                    falha = classificar(erro, tentativas + 1, self.config.retry_base, self.config.retry_max)
                    proxima = time.time() + falha.espera
                    await self.estado.falhar_resolucao(nome, proxima, falha.motivo)
                    indisponiveis += 1
                    log("canal_indisponivel", canal=nome, motivo=falha.motivo, proxima=proxima)
            self._ids_por_nome = {n: v for n, v in self._ids_por_nome.items() if n in solicitados}
            await self.estado.ativar_canais(list(novos))
            mudaram = set(novos) != set(self.ativos)
            self.ativos = novos
            if mudaram:
                self.acordar.set()
            log("canais_atualizados", ativos=len(novos), indisponiveis=indisponiveis)

    async def rodada(self) -> int:
        """Um orçamento por canal por rodada; deadlines persistidos evitam loops agressivos."""
        async with self._rodada_lock:
            quantidade = 0
            for snapshot in await self.estado.canais():
                canal = await self.estado.canal(snapshot["canal_id"])
                if not canal or not canal["ativo"] or canal["proxima"] > time.time():
                    continue
                geracao = canal["geracao"]
                try:
                    if canal["limite"] is None:
                        canal["limite"] = max(canal["cursor"], await self.telegram.mais_nova(canal["canal_id"]))
                        if not await self.estado.iniciar_varredura(canal["canal_id"], canal["limite"], geracao):
                            continue
                    # O RPC anterior e seu commit podem ter cedido ao refresh.
                    atual = await self.estado.canal(canal["canal_id"])
                    if not atual["ativo"] or atual["geracao"] != geracao:
                        continue
                    pagina = await self.telegram.pagina(canal, self.config.recuperacao_lote)
                    mensagens, esgotou = pagina
                    ids = [msg.msg_id for msg in mensagens]
                    if ids != sorted(set(ids)) or any(i <= canal["cursor"] or i > canal["limite"] for i in ids):
                        raise ValueError("pagina_fora_da_cobertura")
                    cursor = canal["limite"] if esgotou else (ids[-1] if ids else canal["cursor"])
                    if isinstance(pagina, PaginaHistorico):
                        cursor = pagina.cursor
                        if not canal["cursor"] <= cursor <= canal["limite"] or any(i > cursor for i in ids):
                            raise ValueError("pagina_fora_da_cobertura")
                    atraso = self.config.recuperacao_intervalo if esgotou else self.config.recuperacao_pausa
                    novos = await self.estado.registrar_pagina(canal["canal_id"], mensagens, cursor,
                        esgotou, time.time() + atraso, geracao)
                    if novos is None:
                        continue
                    quantidade += len(mensagens)
                    self.acordar_ofertas.set()
                    log("historico_registrado", canal_id=canal["canal_id"], coletadas=len(ids), novas=novos,
                        cursor=cursor, limite=canal["limite"], esgotou=esgotou)
                except FalhaLocal:
                    raise
                except Exception as erro:
                    falha = classificar(erro, canal["tentativas"] + 1, self.config.retry_base, self.config.retry_max)
                    segundos = getattr(erro, "seconds", getattr(erro, "segundos", None))
                    minimo_remoto = isinstance(segundos, (int, float)) and segundos >= 0
                    await self.estado.falhar_canal(canal["canal_id"], time.time() + falha.espera,
                        falha.motivo, geracao, minimo_remoto=minimo_remoto)
                    log("historico_falhou", canal_id=canal["canal_id"], motivo=falha.motivo, espera=falha.espera)
            return quantidade

    async def executar(self) -> None:
        while True:
            self.acordar.clear()
            await self.rodada()
            canais = [c for c in await self.estado.canais() if c["ativo"]]
            proxima = min((c["proxima"] for c in canais), default=time.time() + self.config.recuperacao_intervalo)
            try:
                await asyncio.wait_for(self.acordar.wait(), max(0.01, proxima - time.time()))
            except asyncio.TimeoutError:
                pass
