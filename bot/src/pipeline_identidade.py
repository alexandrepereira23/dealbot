"""Fluxo ativo v2; Pipeline legado permanece para decisões antigas e regressões."""

import asyncio
import json
import time

from .avaliacao import avaliar_mensagem
from .dedup import gerar_hash
from .identidade import identificar
from .modelos import FalhaLocal
from .observabilidade import log, motivo_erro
from .pipeline import Pipeline
from .politica import classificar
from .resolvedor import ResolvedorURLs


class MidiaCoordenada:
    """A reserva remota impede novo vínculo à chave antes da remoção física."""

    def __init__(self, armazenamento, repositorio):
        self.armazenamento = armazenamento
        self.repositorio = repositorio

    async def enviar(self, chave, dados):
        return await self.armazenamento.enviar(chave, dados)

    async def remover(self, chave):
        url = await self.armazenamento.url_publica(chave)
        if await self.repositorio.reservar_remocao(url):
            await self.armazenamento.remover(chave)
            await self.repositorio.confirmar_remocao(url)


class PipelineIdentidade(Pipeline):
    def __init__(self, estado, repositorio, armazenamento, telegram, cache, config, *, resolvedor=None):
        super().__init__(estado, repositorio, MidiaCoordenada(armazenamento, repositorio), telegram, cache, config)
        self.resolvedor = resolvedor or ResolvedorURLs(timeout=config.resolucao_timeout,
            max_redirects=config.resolucao_redirects, max_bytes=config.resolucao_max_bytes)
        self.acordar_enriquecimento = asyncio.Event()
        self.ativos["enriquecimento"] = self.max_ativos["enriquecimento"] = 0

    def iniciar(self):
        super().iniciar()
        for indice in range(self.config.enriquecimento_workers):
            task = asyncio.create_task(self._enriquecimentos(), name=f"enriquecimento-{indice}")
            task.add_done_callback(self._terminou)
            self.tasks.append(task)
        task = asyncio.create_task(self._confirmacoes(), name="confirmacoes-remotas")
        task.add_done_callback(self._terminou)
        self.tasks.append(task)

    async def _oferta(self, job):
        # Decisão congelada sem versão nova continua exatamente no caminho legado.
        if job["decisao"] is not None and job.get("identidade") is None:
            if hasattr(self.repositorio, "salvar_legada"):
                resultado = await self._legada(job)
                if resultado.status == "conflito":
                    raise RuntimeError("decisao_legada_conflitante")
                await self.estado.vincular(job, resultado.produto_id)
                await self.estado.finalizar_oferta(job, "duplicata" if resultado.status == "duplicado" else "aprovada",
                    resultado.produto_id, midia=bool(job["tem_foto"] and not resultado.foto_url
                    and resultado.status != "removido"), resultado=resultado.status)
                self.acordar_midias.set()
                return
            return await super()._oferta(job)
        if job["decisao"] is None:
            if self.cache.preparados is None:
                await self.estado.adiar_oferta(job, "aguardando_config", 0, "filtros_indisponiveis")
                return
            contexto = json.loads(job.get("contexto") or "{}")
            avaliada = avaliar_mensagem(job["texto"], self.cache.preparados, contexto,
                canal_id=job["canal_id"], username=job["username"])
            diagnostico = {**avaliada.diagnostico, "snapshot": self.cache.versao}
            if not avaliada.aceita:
                await self.estado.finalizar_oferta(job, "descartada", resultado=diagnostico["motivo"], diagnostico=diagnostico)
                return
            produto = avaliada.extracao.produto
            url = produto.get("link")
            cached = await self.estado.cache_url(url, time.time()) if url else None
            identidade = identificar(produto, job["texto"], contexto,
                url_resolvida=cached.get("url_final") if cached and cached.get("estado") == "positivo" else None)
            identidade["enriquecer"] = bool(url and identidade.get("chave") is None and not identidade.get("copia"))
            hash_legado = gerar_hash(produto)
            await self.estado.decidir(job, produto, hash_legado, diagnostico, identidade)
            job = {**job, "hash": hash_legado, "identidade": json.dumps(identidade)}
        else:
            produto = json.loads(job["decisao"])
            identidade = json.loads(job["identidade"])
        resultado = await self.repositorio.salvar_identificada(job, produto, identidade, self.config.janela_oferta_horas)
        if resultado.status == "conflito":
            raise RuntimeError("decisao_remota_conflitante")
        # Vínculo antecede filas; crash entre esses checkpoints retoma a mesma RPC/evento.
        await self.estado.vincular(job, resultado.produto_id)
        if identidade.get("enriquecer") and resultado.status != "removido":
            await self.estado.agendar_enriquecimento(job, resultado.produto_id, produto["link"])
        duplicado = resultado.status in {"duplicado", "atualizado"}
        await self.estado.finalizar_oferta(job, "duplicata" if duplicado else "aprovada", resultado.produto_id,
            midia=bool(job["tem_foto"] and not resultado.foto_url and resultado.status != "removido"), resultado=resultado.status)
        self.acordar_midias.set()
        self.acordar_enriquecimento.set()
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        log("oferta_identificada", canal_id=job["canal_id"], msg_id=job["msg_id"], produto_id=resultado.produto_id,
            versao=2, motivo=identidade["motivo"], resultado=resultado.status,
            latencia_local_ms=round((evento["disponibilizado_em"] - job["recebido_em"]) * 1000, 2))

    async def _enriquecimentos(self):
        while not self.parando:
            self.acordar_enriquecimento.clear()
            job = await self.estado.obter_enriquecimento(time.time())
            if job is None:
                try:
                    await asyncio.wait_for(self.acordar_enriquecimento.wait(), .5)
                except asyncio.TimeoutError:
                    pass
                continue
            self.ativos["enriquecimento"] += 1
            self.max_ativos["enriquecimento"] = max(self.max_ativos["enriquecimento"], self.ativos["enriquecimento"])
            try:
                await self._enriquecer(job)
            except asyncio.CancelledError:
                await self.estado.atualizar_enriquecimento(job, estado="retry", proxima=time.time())
                raise
            except FalhaLocal:
                raise
            except Exception as erro:
                # Falha de RPC é retry durável; não consome novamente orçamento HTTP.
                tentativas = job.get("tentativas_rpc", 0) + 1
                falha = classificar(erro, tentativas, self.config.retry_base, self.config.retry_max)
                await self.estado.atualizar_enriquecimento(job, estado="retry", proxima=time.time() + falha.espera,
                    erro=falha.motivo, tentativas_rpc=tentativas)
                log("enriquecimento_falhou", canal_id=job["canal_id"], msg_id=job["msg_id"], motivo=falha.motivo)
            finally:
                self.ativos["enriquecimento"] -= 1

    async def _enriquecer(self, job):
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        if evento is None:
            raise FalhaLocal("fonte_enriquecimento_ausente")
        resultado = json.loads(job["resultado"]) if job.get("resultado") else await self.estado.cache_url(job["url"], time.time())
        if resultado is None:
            tentativa = job["tentativas"] + 1
            # Registrar tentativa antes da rede: crash não recupera orçamento já gasto.
            if tentativa > self.config.resolucao_tentativas:
                await self.estado.atualizar_enriquecimento(job, estado="esgotado", finalizado_em=time.time())
                return
            await self.estado.atualizar_enriquecimento(job, tentativas=tentativa)
            try:
                resultado = await asyncio.wait_for(self.resolvedor.resolver(job["url"]), self.config.resolucao_timeout)
            except Exception as erro:
                resultado = {"estado": "negativo", "url_final": None, "motivo": motivo_erro(erro)}
            ttl = self.config.resolucao_cache_positivo if resultado["estado"] == "positivo" else self.config.resolucao_cache_negativo
            await self.estado.guardar_cache_url(job["url"], resultado, time.time() + ttl)
        # Resultado de rede é checkpoint separado do efeito de reconciliação.
        await self.estado.atualizar_enriquecimento(job, resultado=json.dumps(resultado))
        if resultado["estado"] == "positivo":
            produto = json.loads(evento["decisao"])
            identidade = identificar(produto, evento["texto"], json.loads(evento["contexto"]), url_resolvida=resultado["url_final"])
            congelada = json.loads(evento.get("identidade") or "{}")
            if congelada.get("copia_versao") != 1:
                # Checkpoints anteriores não aderem silenciosamente à regra nova.
                identidade.pop("copia", None)
                identidade.pop("copia_versao", None)
            if identidade.get("chave") is not None or identidade.get("copia"):
                reconciliada = await self.repositorio.enriquecer(job, identidade)
                resultado["reconciliacao"] = {"status": reconciliada.status, "produto_id": reconciliada.produto_id}
            else:
                resultado["reconciliacao"] = {"status": "identidade_insuficiente", "motivo": identidade["motivo"]}
            await self.estado.atualizar_enriquecimento(job, resultado=json.dumps(resultado))
            log("identidade_reconciliada", canal_id=job["canal_id"], msg_id=job["msg_id"],
                resultado=resultado["reconciliacao"]["status"], motivo=identidade["motivo"])
        elif resultado.get("motivo") in {"timeout", "TimeoutError", "ConnectionError", "OSError", "falha_transporte", "dns_ocupado"}:
            tentativa = job["tentativas"] + (0 if job.get("resultado") else 1)
            if tentativa < self.config.resolucao_tentativas:
                await self.estado.atualizar_enriquecimento(job, estado="retry", resultado=None,
                    proxima=time.time() + self.config.resolucao_cache_negativo)
                return
        await self.estado.atualizar_enriquecimento(job, estado="concluido", finalizado_em=time.time(), erro=None)

    async def _confirmacoes(self):
        tentativas = 0
        while not self.parando:
            espera = self.config.retry_base
            try:
                job = await self.estado.obter_confirmacao()
                if job:
                    await self.repositorio.confirmar_evento(job)
                    await self.estado.confirmar_remoto(job)
                    tentativas = 0
                    continue
            except asyncio.CancelledError:
                raise
            except FalhaLocal:
                raise
            except Exception as erro:
                tentativas += 1
                espera = classificar(erro, tentativas, self.config.retry_base, self.config.retry_max).espera
                log("confirmacao_remota_pendente", motivo=motivo_erro(erro))
            await asyncio.sleep(espera)

    async def _legada(self, job):
        produto = json.loads(job["decisao"])
        hash_legado = job["hash"] if job.get("hash") is not None else gerar_hash(produto)
        aliases = await self.estado.aliases(job["canal_id"])
        resultado = await self.repositorio.salvar_legada(job, produto, hash_legado, aliases)
        if resultado.status != "conflito":
            await self.estado.fixar_referencia(job)
        return resultado

    async def preparar_legados(self):
        """Pin dos jobs antigos antes de habilitar limpeza de legado ou recepção.

        Não lê/refiltra texto: envia somente decisões/hash já congelados. O gate
        remoto impede que o limpador apague dados enquanto este preflight migra.
        """
        if not hasattr(self.repositorio, "salvar_legada"):
            return  # Adaptadores offline explícitos; produção usa RepositorioIdentidade.
        while True:
            lote = await self.estado.legados_recuperaveis()
            if not lote:
                break
            for job in lote:
                resultado = await self._legada(job)
                if resultado.status == "conflito":
                    raise RuntimeError("legado_recuperavel_conflitante")
                await asyncio.sleep(0)
        await self.repositorio.legados_prontos()

    async def encerrar(self):
        self.acordar_enriquecimento.set()
        await super().encerrar()
        fechar = getattr(self.resolvedor, "aclose", None)
        if fechar:
            await fechar()
