"""DEALBOT: entrada durável, ofertas contínuas e mídia fora do caminho crítico."""

import asyncio
import logging
import signal
import time
from typing import Any, Callable

from .cache import CacheFiltros
from .config import Config, obrigatoria
from .db import criar_cliente, fechar_cliente
from .estado import EstadoLocal
from .midia import ArmazenamentoSupabase
from .modelos import FalhaLocal
from .observabilidade import log, motivo_erro
from .pipeline import Pipeline
from .politica import classificar
from .recuperacao import Recuperacao
from .repository import RepositorioSupabase
from .telegram import Telegram


class FilaUpdatesLimitada(asyncio.Queue):
    """Backpressure do transporte 1.36: overflow explícito força reconciliação.

    O sender usa put_nowait. Não lançar QueueFull dentro dele: sinalizar supervisor,
    que desconecta/limpa a fila limitada e recupera a cobertura pelo histórico.
    A mensagem excedente não foi aceita localmente; nunca move nossa fronteira.
    """

    def __init__(self, limite: int, sobrecarga: asyncio.Event) -> None:
        super().__init__(maxsize=limite)
        self.sobrecarga = sobrecarga

    def put_nowait(self, item: Any) -> None:
        if self.full():
            self.sobrecarga.set()
            return
        super().put_nowait(item)


def limitar_updates(client: Any, limite: int, sobrecarga: asyncio.Event) -> None:
    """Adaptação interna pequena e testada para a versão FIXADA do Telethon.

    Não existe limite público dessa fila no 1.36. Falhar se o contrato mudar,
    em vez de alegar um limite que só existe depois da recepção.
    """
    if not hasattr(client, "_updates_queue") or not hasattr(client._sender, "_updates_queue"):
        raise RuntimeError("telethon_sem_fila_compativel")
    fila = FilaUpdatesLimitada(limite, sobrecarga)
    client._updates_queue = fila
    client._sender._updates_queue = fila


async def periodico(operacao: Callable, intervalo: float, config: Config,
                    nome: str, acordar: asyncio.Event | None = None) -> None:
    tentativas = 0
    while True:
        try:
            await operacao()
            tentativas = 0
            espera = intervalo
            if acordar is not None:
                acordar.set()
        except FalhaLocal:
            raise
        except Exception as erro:
            tentativas += 1
            falha = classificar(erro, tentativas, config.retry_base, config.retry_max)
            espera = max(intervalo, falha.espera)
            log("atualizacao_falhou", componente=nome, motivo=falha.motivo, espera=espera)
            dono = getattr(operacao, "__self__", None)
            if isinstance(dono, CacheFiltros):
                log("filtros_snapshot_mantido", versao=dono.versao, idade_s=dono.idade())
        await asyncio.sleep(espera)


async def supervisionar_conexao(telegram: Telegram, recuperacao: Recuperacao,
                                sobrecarga: asyncio.Event, config: Config) -> None:
    saudavel = False
    tentativas = 0
    while True:
        try:
            if sobrecarga.is_set():
                log("recepcao_sobrecarga", acao="desconectar_e_recuperar")
                await telegram.client.disconnect()
                fila = telegram.client._updates_queue
                while not fila.empty():
                    fila.get_nowait()
                sobrecarga.clear()
                saudavel = False
                await asyncio.sleep(max(config.retry_base, 1))
            if not await telegram.saudavel():
                raise ConnectionError("telegram_sem_resposta")
            if not saudavel:
                log("telegram_conectado", acao="conferir_historico")
                await recuperacao.estado.acordar_canais()
                recuperacao.acordar.set()
            saudavel = True
            tentativas = 0
            # Acorda imediatamente se o transporte sinalizar overflow.
            try:
                await asyncio.wait_for(sobrecarga.wait(), min(5, config.recuperacao_intervalo))
            except asyncio.TimeoutError:
                pass
        except FalhaLocal:
            raise
        except Exception as erro:
            saudavel = False
            tentativas += 1
            falha = classificar(erro, tentativas, config.retry_base, config.retry_max)
            log("telegram_indisponivel", motivo=falha.motivo, espera=falha.espera)
            await asyncio.sleep(falha.espera)


async def servir(client: Any, estado: EstadoLocal, repositorio: Any, armazenamento: Any,
                 config: Config, parar: asyncio.Event, sobrecarga: asyncio.Event) -> None:
    """Composição testável: tarefas são supervisionadas e encerradas antes do estado."""
    from telethon import events

    telegram = Telegram(client, estado, config.rede_timeout)
    cache = CacheFiltros(repositorio, config.rede_timeout)
    pipeline = Pipeline(estado, repositorio, armazenamento, telegram, cache, config)
    recuperacao = Recuperacao(estado, repositorio, telegram, config, pipeline.acordar_ofertas)
    tasks: list[asyncio.Task] = []
    recepcao_fatal = asyncio.get_running_loop().create_future()

    async def handler(event: Any) -> None:
        if parar.is_set() or event.chat_id not in recuperacao.ativos:
            return
        try:
            await pipeline.receber(telegram.envelope(event.message, event.chat_id,
                recuperacao.ativos[event.chat_id], "live"))
        except Exception as erro:
            # Falhar fechado para qualquer evento que não pôde ser duravelmente aceito.
            log("recepcao_falhou", canal_id=event.chat_id, msg_id=event.message.id, motivo=motivo_erro(erro))
            if not recepcao_fatal.done():
                recepcao_fatal.set_result(erro)

    async def manutencao() -> None:
        removidos = await estado.limpar(time.time() - config.retencao_dias * 86400)
        log("estado_local", removidos=removidos, workers=pipeline.ativos, **await estado.resumo())

    client.add_event_handler(handler, events.NewMessage())
    pipeline.iniciar()
    try:
        # connect + autorização, nunca start() interativo esperando telefone/código no serviço.
        await asyncio.wait_for(client.connect(), config.rede_timeout)
        if not await asyncio.wait_for(client.is_user_authorized(), config.rede_timeout):
            raise RuntimeError("sessao_telegram_nao_autorizada")
        tasks = [
            asyncio.create_task(periodico(cache.atualizar, config.filtros_intervalo, config,
                "filtros", pipeline.acordar_ofertas), name="cache-filtros"),
            asyncio.create_task(periodico(recuperacao.atualizar_canais, config.canais_intervalo, config,
                "canais"), name="cache-canais"),
            asyncio.create_task(recuperacao.executar(), name="recuperacao"),
            asyncio.create_task(supervisionar_conexao(telegram, recuperacao, sobrecarga, config), name="conexao"),
            asyncio.create_task(periodico(manutencao, config.limpeza_intervalo, config,
                "manutencao"), name="manutencao"),
            asyncio.create_task(parar.wait(), name="sinais"),
        ]
        concluidas, _ = await asyncio.wait([*tasks, pipeline.fatal, recepcao_fatal], return_when=asyncio.FIRST_COMPLETED)
        for futuro in concluidas:
            if futuro in (pipeline.fatal, recepcao_fatal):
                raise futuro.result()
            if futuro.exception() is not None:
                raise futuro.exception()
    finally:
        parar.set()
        client.remove_event_handler(handler)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(client.disconnect(), config.rede_timeout)
        finally:
            await pipeline.encerrar()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from dotenv import load_dotenv
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon import __version__ as telethon_versao

    load_dotenv()
    if telethon_versao != "1.36.0":
        raise RuntimeError("versao_telethon_nao_validada")
    config = Config.carregar()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for nome in ("telethon", "httpx", "httpcore", "supabase", "storage3", "postgrest", "gotrue"):
        logging.getLogger(nome).setLevel(logging.CRITICAL)
    parar = asyncio.Event()
    sobrecarga = asyncio.Event()
    for sinal in (signal.SIGTERM, signal.SIGINT):
        # signal.signal funciona também no loop Windows; só instalar na thread principal.
        signal.signal(sinal, lambda recebido, frame: parar.set())
    estado = EstadoLocal(config.state_dir, config.buffer_max, config.prioridade_live_cota)
    remoto = None
    try:
        await estado.abrir()
        remoto = await criar_cliente(obrigatoria("SUPABASE_URL"), obrigatoria("SUPABASE_SERVICE_KEY"),
                                     config.rede_timeout, config.midia_timeout)
        client = TelegramClient(StringSession(obrigatoria("TG_SESSION_STRING")),
            int(obrigatoria("TG_API_ID")), obrigatoria("TG_API_HASH"),
            sequential_updates=True, flood_sleep_threshold=0, request_retries=0,
            raise_last_call_error=True, timeout=config.rede_timeout)
        limitar_updates(client, config.buffer_max, sobrecarga)
        await servir(client, estado, RepositorioSupabase(remoto, config.rede_timeout),
                     ArmazenamentoSupabase(remoto, config.midia_timeout), config, parar, sobrecarga)
    finally:
        try:
            if remoto is not None:
                await fechar_cliente(remoto)
        finally:
            await estado.fechar()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as erro:
        log("processo_interrompido", motivo=motivo_erro(erro))
        raise SystemExit(1) from None
