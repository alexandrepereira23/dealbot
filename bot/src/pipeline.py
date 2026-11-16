"""Workers acompanhados; SQLite é a fila, eventos em memória só acordam leitores."""

import asyncio
import json
import time
from collections.abc import Coroutine
from typing import Any, TypeVar

from .avaliacao import avaliar_mensagem
from .cache import CacheFiltros
from .config import Config
from .dedup import gerar_hash
from .estado import EstadoLocal
from .modelos import Aguardar, ErroPermanente, FalhaLocal, Mensagem
from .observabilidade import log
from .politica import classificar
from .repository import CAMPOS_PRODUTO


TControle = TypeVar("TControle")


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
        self._controles: set[asyncio.Task] = set()
        self.fatal: asyncio.Future | None = None
        self.ativos = {"oferta": 0, "midia": 0}
        self.max_ativos = {"oferta": 0, "midia": 0}

    def iniciar(self) -> None:
        """Cria workers fixos; controles de claim/devolução são drenados em série."""
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

    @staticmethod
    async def _concluir_controle(tarefa: asyncio.Task[TControle]) -> TControle:
        """Drena a mesma operação, inclusive sob cancelamentos repetidos."""
        while not tarefa.done():
            try:
                await asyncio.shield(tarefa)
            except asyncio.CancelledError:
                pass
        # Erro local não vira cancelamento bem-sucedido; sobe ao supervisor.
        return tarefa.result()

    def _criar_controle(self, operacao: Coroutine[Any, Any, TControle]) -> asyncio.Task[TControle]:
        # A operação pertence ao mesmo worker fixo, inclusive para observadores
        # de interleavings. Auxiliares são identificadas por este conjunto, não
        # por substituir o nome do proprietário por uma classe genérica.
        dono = asyncio.current_task()
        tarefa = asyncio.create_task(operacao, name=dono.get_name() if dono else None)
        self._controles.add(tarefa)
        tarefa.add_done_callback(self._controles.discard)
        return tarefa

    async def _devolver_protegido(self, classe: str, job: dict) -> None:
        tarefa = self._criar_controle(self._devolver(classe, job))
        await self._concluir_controle(tarefa)

    async def _reivindicar(self, classe: str) -> dict | None:
        # Uma única auxiliar de controle por worker, sem fan-out por item da
        # inbox. Não começa outra aquisição/devolução antes de drenar esta.
        obter = (self.estado.obter_oferta(time.time(), self.cache.filtros is not None)
                 if classe == "oferta" else self.estado.obter_midia(time.time()))
        tarefa = self._criar_controle(obter)
        try:
            return await asyncio.shield(tarefa)
        except asyncio.CancelledError:
            job = await self._concluir_controle(tarefa)
            if job is not None:
                await self._devolver_protegido(classe, job)
            raise

    async def _worker(self, classe: str) -> None:
        evento = self.acordar_ofertas if classe == "oferta" else self.acordar_midias
        while not self.parando:
            # Clear antes do SELECT evita perder notificação entre consulta e espera.
            evento.clear()
            job = await self._reivindicar(classe)
            if job is None:
                await self._esperar(classe, evento)
                continue
            if self.parando:
                await self._devolver_protegido(classe, job)
                break
            self.ativos[classe] += 1
            self.max_ativos[classe] = max(self.max_ativos[classe], self.ativos[classe])
            inicio = time.monotonic()
            log("trabalho_iniciado", classe=classe, canal_id=job["canal_id"], msg_id=job["msg_id"],
                tentativa=job["tentativas"], espera_ms=round(max(0, time.time() - job.get("recebido_em", time.time())) * 1000, 2))
            try:
                try:
                    if classe == "oferta":
                        await self._oferta(job)
                    else:
                        await self._midia(job)
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
            except asyncio.CancelledError:
                # Abrange também os awaits do tratamento de erro acima, não só
                # o caminho feliz. Sem isso, novo cancelamento perde o claim.
                await self._devolver_protegido(classe, job)
                raise
            finally:
                self.ativos[classe] -= 1
                log("trabalho_finalizado", classe=classe, canal_id=job["canal_id"], msg_id=job["msg_id"],
                    duracao_ms=round((time.monotonic() - inicio) * 1000, 2))

    async def _devolver(self, classe: str, job: dict) -> None:
        if classe == "oferta":
            await self.estado.adiar_oferta(job, "retry", time.time(), "encerramento")
        else:
            await self.estado.atualizar_midia(job["produto_id"], estado="retry", proxima=time.time(), erro="encerramento")

    def _destino_midia(self, job: dict):
        """Fakes antigos não recebem job; adaptador coordenado recebe destino congelado."""
        seletor = getattr(self.armazenamento, "para", None)
        return seletor(job.get("destino", "supabase")) if seletor else self.armazenamento

    async def _enviar_midia(self, job: dict, dados: bytes) -> str:
        enviar_job = getattr(self.armazenamento, "enviar_job", None)
        if enviar_job:
            return await enviar_job(job, dados)
        return await self._destino_midia(job).enviar(job["chave"], dados)

    async def _remover_midia(self, job: dict) -> None:
        remover_job = getattr(self.armazenamento, "remover_job", None)
        if remover_job:
            await remover_job(job)
            return
        await self._destino_midia(job).remover(job["chave"])

    async def _publicacao_local_conhecida(self, job: dict) -> bool:
        """Somente o adaptador local consegue provar publicação sem rede."""
        if job.get("destino", "supabase") != "local":
            return False
        publicada_job = getattr(self.armazenamento, "publicada_job", None)
        if publicada_job:
            return bool(await publicada_job(job))
        publicada = getattr(self._destino_midia(job), "publicada", None)
        if publicada is None:
            raise RuntimeError("publicacao_local_indisponivel")
        return bool(await publicada(job["chave"]))

    async def _url_publica_midia(self, job: dict) -> str:
        """Consulta por job também atravessa o wrapper, sem perder o destino."""
        url_publica_job = getattr(self.armazenamento, "url_publica_job", None)
        if url_publica_job:
            return await url_publica_job(job)
        return await self._destino_midia(job).url_publica(job["chave"])

    async def _oferta(self, job: dict) -> None:
        if job["decisao"] is None:
            if self.cache.filtros is None:
                await self.estado.adiar_oferta(job, "aguardando_config", 0, "filtros_indisponiveis")
                return
            contexto = json.loads(job.get("contexto") or "{}")
            preparados = self.cache.preparados
            if preparados is None:
                raise FalhaLocal("snapshot_preparado_ausente")
            resultado_local = avaliar_mensagem(job["texto"], preparados, contexto,
                canal_id=job["canal_id"], username=job["username"])
            diagnostico = {**resultado_local.diagnostico, "snapshot": self.cache.versao}
            if not resultado_local.aceita:
                motivo = diagnostico["motivo"]
                await self.estado.finalizar_oferta(job, "descartada", resultado=motivo,
                                                   diagnostico=diagnostico)
                log("oferta_descartada", canal_id=job["canal_id"], msg_id=job["msg_id"],
                    motivo=motivo, diagnostico=diagnostico)
                return
            produto = resultado_local.extracao.produto
            hash_oferta = gerar_hash(produto)
            await self.estado.decidir(job, produto, hash_oferta, diagnostico=diagnostico)
            log("oferta_decidida", canal_id=job["canal_id"], msg_id=job["msg_id"],
                motivo=diagnostico["motivo"], regra=diagnostico["regra"])
        else:
            produto = json.loads(job["decisao"])
            # O hash persistido pertence à decisão, não à versão do extrator ou
            # ao snapshot corrente. Fallback só para decisão legada sem hash.
            hash_oferta = job["hash"] if job.get("hash") is not None else gerar_hash(produto)
        if not await self.estado.reservar_hash(job, hash_oferta):
            raise Aguardar(self.config.retry_base, "hash_em_reconciliacao")
        registro = {campo: produto[campo] for campo in CAMPOS_PRODUTO if campo in produto}
        registro.update(canal_origem=job["remoto_canal"], telegram_msg_id=job["msg_id"],
                        raw_text=job["texto"][:2000], data_oferta=job["data_origem"],
                        foto_url=None, dedup_hash=hash_oferta)
        aliases = await self.estado.aliases(job["canal_id"])
        async def ao_vincular(produto_id: int) -> None:
            await self.estado.vincular(job, produto_id)
        resultado = await self.repositorio.salvar_oferta(registro, aliases,
            produto_id=job["produto_id"], ao_vincular=ao_vincular)
        duplicata = resultado.status == "duplicado"
        await self.estado.finalizar_oferta(job, "duplicata" if duplicata else "aprovada",
            resultado.produto_id, midia=bool(job["tem_foto"] and not resultado.foto_url), resultado=resultado.status,
            destino_midia=self.config.midia_modo)
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
        # No destino local, intenção sem URL pode significar crash após link(2),
        # mas antes do checkpoint. Confere o final antes de baixar de novo ou de
        # reservar tombstone para um objeto que talvez nem exista.
        if (job["compensar"] and job.get("destino") == "local" and not job["enviado"]
                and job["url"] is None):
            if await self._publicacao_local_conhecida(job):
                url_local = await self._url_publica_midia(job)
                await self.estado.atualizar_midia(produto_id, enviado=1, url=url_local, compensar=0)
                job = {**job, "enviado": 1, "url": url_local, "compensar": 0}
            elif job["falha_apos_limpeza"]:
                await self.estado.atualizar_midia(produto_id, estado="falha_permanente", compensar=0,
                    erro=job["falha_apos_limpeza"], finalizado_em=time.time())
                return
            else:
                await self.estado.atualizar_midia(produto_id, estado="retry", compensar=0,
                    proxima=time.time(), erro="publicacao_local_ausente")
                return
        if job["compensar"]:
            # Só remover a chave conhecida se não for a foto atualmente vinculada.
            if not produto or job["url"] is None or produto.get("foto_url") != job["url"]:
                await self._remover_midia(job)
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
                await self._remover_midia(job)
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
            url = await self._enviar_midia(job, dados)
            await self.estado.atualizar_midia(produto_id, enviado=1, url=url, compensar=0)
        else:
            url = job["url"]
        situacao = await self.repositorio.vincular_foto(produto_id, url)
        if situacao != "atualizada":
            atual = await self.repositorio.buscar_produto(produto_id)
            if atual is None or atual.get("foto_url") != url:
                await self.estado.atualizar_midia(produto_id, compensar=1)
                await self._remover_midia(job)
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
