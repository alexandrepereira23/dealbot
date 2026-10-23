"""Workers acompanhados; SQLite é a fila, eventos em memória só acordam leitores."""

import asyncio
import json
import time
from typing import Any

from .cache import CacheFiltros
from .config import Config
from .dedup import gerar_hash
from .estado import EstadoLocal
from .extractor import extrair_produto
from .filters import passa_no_filtro
from .modelos import Aguardar, ErroPermanente, FalhaLocal, Mensagem
from .observabilidade import log
from .politica import classificar


class Pipeline:
    """Quantidade fixa de workers de oferta/mídia, com retomada após cancelamento."""

    def __init__(self, estado: EstadoLocal, repositorio: Any, armazenamento: Any,
                 telegram: Any, cache: CacheFiltros, config: Config) -> None:
        self.estado = estado
        self.repositorio = repositorio
        self.armazenamento = armazenamento
        self.telegram = telegram
        self.cache = cache
        self.config = config
        self.acordar_ofertas = asyncio.Event()
        self.acordar_midias = asyncio.Event()
        self.parando = False
        self.tasks: list[asyncio.Task] = []
        self.fatal: asyncio.Future | None = None
        self.ativos = {"oferta": 0, "midia": 0}
        self.max_ativos = {"oferta": 0, "midia": 0}

    def iniciar(self) -> None:
        """Cria somente workers fixos, nunca uma task por mensagem."""
        self.fatal = asyncio.get_running_loop().create_future()
        for classe, quantidade in (("oferta", self.config.oferta_workers), ("midia", self.config.midia_workers)):
            for indice in range(quantidade):
                task = asyncio.create_task(self._worker(classe), name=f"{classe}-{indice}")
                task.add_done_callback(self._terminou)
                self.tasks.append(task)

    def _terminou(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            erro = task.exception()
            if erro is not None and self.fatal is not None and not self.fatal.done():
                # Resultado (não exception) evita exceção não observada no Future de supervisão.
                self.fatal.set_result(erro)

    async def receber(self, msg: Mensagem) -> bool:
        """Notifica só depois da gravação durável; falha local sobe ao supervisor."""
        if self.parando:
            return False
        canal = await self.estado.canal(msg.canal_id)
        geracao = canal["geracao"] if canal is not None else None
        novo = await self.estado.registrar(msg, geracao=geracao)
        if novo is None:
            log("mensagem_ignorada", canal_id=msg.canal_id, msg_id=msg.msg_id,
                origem=msg.origem, motivo="canal_inativo_ou_geracao_encerrada")
            return False
        self.acordar_ofertas.set()
        log("mensagem_recebida", canal_id=msg.canal_id, msg_id=msg.msg_id, origem=msg.origem,
            nova=novo, data_origem=msg.data_origem, recebido_em=msg.recebido_em)
        return novo

    async def _esperar(self, classe: str, evento: asyncio.Event) -> None:
        proxima = await self.estado.proxima_tentativa(classe, self.cache.filtros is not None)
        timeout = None if proxima is None else max(0.001, proxima - time.time())
        try:
            await asyncio.wait_for(evento.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    async def _worker(self, classe: str) -> None:
        evento = self.acordar_ofertas if classe == "oferta" else self.acordar_midias
        while not self.parando:
            # Clear antes do SELECT evita perder notificação entre consulta e espera.
            evento.clear()
            job = (await self.estado.obter_oferta(time.time(), self.cache.filtros is not None)
                   if classe == "oferta" else await self.estado.obter_midia(time.time()))
            if job is None:
                await self._esperar(classe, evento)
                continue
            if self.parando:
                await self._devolver(classe, job)
                break
            self.ativos[classe] += 1
            self.max_ativos[classe] = max(self.max_ativos[classe], self.ativos[classe])
            inicio = time.monotonic()
            log("trabalho_iniciado", classe=classe, canal_id=job["canal_id"], msg_id=job["msg_id"],
                tentativa=job["tentativas"], espera_ms=round(max(0, time.time() - job.get("recebido_em", time.time())) * 1000, 2))
            try:
                if classe == "oferta":
                    await self._oferta(job)
                else:
                    await self._midia(job)
            except asyncio.CancelledError:
                await self._devolver(classe, job)
                raise
            except FalhaLocal:
                # Sem armazenamento confiável, não inventar um retry gravado.
                raise
            except Exception as erro:
                falha = classificar(erro, job["tentativas"], self.config.retry_base, self.config.retry_max)
                proxima = time.time() + falha.espera
                situacao = "falha_permanente" if falha.permanente else "retry"
                if classe == "oferta":
                    if falha.permanente:
                        # Manter motivo e decisão; liberar owner só quando não houve efeito ambíguo.
                        await self.estado.finalizar_oferta(job, situacao, resultado=falha.motivo)
                    else:
                        await self.estado.adiar_oferta(job, situacao, proxima, falha.motivo)
                else:
                    # Compensação pendente nunca vira terminal por falha de limpeza.
                    atual = await self.estado.midia(job["produto_id"])
                    if atual and falha.permanente and atual["enviado"] and not atual["compensar"]:
                        # Upload confirmado também exige reconciliação quando o
                        # erro seguinte é permanente. A foto pode ter sido
                        # vinculada antes de a resposta se perder: o worker de
                        # compensação verifica isso antes de remover o objeto.
                        await self.estado.atualizar_midia(job["produto_id"],
                            compensar=1, falha_apos_limpeza=falha.motivo)
                        atual["compensar"] = 1
                        atual["falha_apos_limpeza"] = falha.motivo
                    if atual and atual["compensar"]:
                        if falha.permanente and not atual["falha_apos_limpeza"]:
                            await self.estado.atualizar_midia(job["produto_id"], falha_apos_limpeza=falha.motivo)
                        situacao = "retry"
                    await self.estado.atualizar_midia(job["produto_id"], estado=situacao,
                        proxima=proxima, erro=falha.motivo,
                        finalizado_em=time.time() if situacao == "falha_permanente" else None)
                log("trabalho_falhou", classe=classe, canal_id=job["canal_id"], msg_id=job["msg_id"],
                    motivo=falha.motivo, estado=situacao, tentativa=job["tentativas"], proxima=proxima)
            finally:
                self.ativos[classe] -= 1
                log("trabalho_finalizado", classe=classe, canal_id=job["canal_id"], msg_id=job["msg_id"],
                    duracao_ms=round((time.monotonic() - inicio) * 1000, 2))

    async def _devolver(self, classe: str, job: dict) -> None:
        if classe == "oferta":
            await self.estado.adiar_oferta(job, "retry", time.time(), "encerramento")
        else:
            await self.estado.atualizar_midia(job["produto_id"], estado="retry", proxima=time.time(), erro="encerramento")

    async def _oferta(self, job: dict) -> None:
        if job["decisao"] is None:
            if self.cache.filtros is None:
                await self.estado.adiar_oferta(job, "aguardando_config", 0, "filtros_indisponiveis")
                return
            produto = await extrair_produto(job["texto"])
            if not produto or not passa_no_filtro(produto, self.cache.filtros):
                motivo = "sem_produto" if not produto else "filtro"
                await self.estado.finalizar_oferta(job, "descartada", resultado=motivo)
                log("oferta_descartada", canal_id=job["canal_id"], msg_id=job["msg_id"], motivo=motivo)
                return
            await self.estado.decidir(job, produto, gerar_hash(produto))
        else:
            produto = json.loads(job["decisao"])
        hash_oferta = gerar_hash(produto)
        if not await self.estado.reservar_hash(job, hash_oferta):
            raise Aguardar(self.config.retry_base, "hash_em_reconciliacao")
        registro = {**produto, "canal_origem": job["remoto_canal"], "telegram_msg_id": job["msg_id"],
                    "raw_text": job["texto"][:2000], "data_oferta": job["data_origem"], "foto_url": None}
        aliases = await self.estado.aliases(job["canal_id"])
        async def ao_vincular(produto_id: int) -> None:
            await self.estado.vincular(job, produto_id)
        resultado = await self.repositorio.salvar_oferta(registro, aliases,
            produto_id=job["produto_id"], ao_vincular=ao_vincular)
        duplicata = resultado.status == "duplicado"
        await self.estado.finalizar_oferta(job, "duplicata" if duplicata else "aprovada",
            resultado.produto_id, midia=bool(job["tem_foto"] and not resultado.foto_url), resultado=resultado.status)
        self.acordar_midias.set()
        self.acordar_ofertas.set()
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        confirmado = evento["disponibilizado_em"] or time.time()
        log("oferta_duplicata" if duplicata else "oferta_disponivel", canal_id=job["canal_id"],
            msg_id=job["msg_id"], produto_id=resultado.produto_id, origem=job["origem"],
            recebido_em=job["recebido_em"], data_origem=job["data_origem"], disponibilizado_em=confirmado,
            latencia_local_ms=round((confirmado - job["recebido_em"]) * 1000, 2), resultado=resultado.status)

    async def _midia(self, job: dict) -> None:
        produto_id = job["produto_id"]
        produto = await self.repositorio.buscar_produto(produto_id)
        if job["compensar"]:
            # Só remover a chave conhecida se não for a foto atualmente vinculada.
            if not produto or job["url"] is None or produto.get("foto_url") != job["url"]:
                await self.armazenamento.remover(job["chave"])
            falha_final = job["falha_apos_limpeza"]
            retentar = produto is not None and not produto.get("foto_url") and not falha_final
            situacao = ("retry" if retentar else "removida" if produto is None else
                        "pronta" if produto.get("foto_url") else "falha_permanente")
            await self.estado.atualizar_midia(produto_id, estado=situacao,
                compensar=0, enviado=0, url=None, proxima=time.time(),
                erro=falha_final,
                finalizado_em=None if retentar else time.time())
            return
        if produto is None or produto.get("foto_url"):
            if job["enviado"] and (produto is None or produto.get("foto_url") != job["url"]):
                await self.estado.atualizar_midia(produto_id, compensar=1)
                await self.armazenamento.remover(job["chave"])
            await self.estado.atualizar_midia(produto_id, estado="pronta" if produto else "removida",
                compensar=0, finalizado_em=time.time(), erro=None)
            return
        if not job["enviado"]:
            dados = await asyncio.wait_for(self.telegram.baixar_foto(job["canal_id"], job["msg_id"],
                self.config.midia_max_bytes), self.config.midia_timeout)
            if dados is None:
                await self.estado.atualizar_midia(produto_id, estado="sem_foto", finalizado_em=time.time())
                return
            if len(dados) > self.config.midia_max_bytes:
                raise ErroPermanente("midia_excede_limite")
            # Gravar intenção ANTES do upload: timeout pode significar objeto já criado.
            await self.estado.atualizar_midia(produto_id, compensar=1)
            url = await self.armazenamento.enviar(job["chave"], dados)
            await self.estado.atualizar_midia(produto_id, enviado=1, url=url, compensar=0)
        else:
            url = job["url"]
        situacao = await self.repositorio.vincular_foto(produto_id, url)
        if situacao != "atualizada":
            atual = await self.repositorio.buscar_produto(produto_id)
            if atual is None or atual.get("foto_url") != url:
                await self.estado.atualizar_midia(produto_id, compensar=1)
                await self.armazenamento.remover(job["chave"])
        await self.estado.atualizar_midia(produto_id, estado="removida" if situacao == "removida" else "pronta",
            compensar=0, erro=None, finalizado_em=time.time())
        log("midia_concluida", produto_id=produto_id, estado=situacao)

    async def encerrar(self) -> None:
        """Drena trabalho em curso por prazo finito; cancela e devolve o restante."""
        self.parando = True
        self.acordar_ofertas.set()
        self.acordar_midias.set()
        if self.tasks:
            _, pendentes = await asyncio.wait(self.tasks, timeout=self.config.shutdown_timeout)
            for task in pendentes:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        log("pipeline_encerrado", **await self.estado.resumo())
