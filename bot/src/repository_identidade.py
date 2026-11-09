"""Contrato remoto v2. Nenhum fallback de RPC/schema para dedup por título."""

from datetime import datetime, timezone

from .repository import CAMPOS_REMOTOS, RepositorioSupabase, ResultadoOferta


class RepositorioIdentidade(RepositorioSupabase):
    async def salvar_legada(self, job: dict, produto: dict, hash_legado: str, aliases: list[str]) -> ResultadoOferta:
        evento = {"canal_id": job["canal_id"], "msg_id": job["msg_id"],
            "canal_origem": job["remoto_canal"], "aliases": self._aliases(job["remoto_canal"], aliases),
            "data_origem": job["data_origem"], "produto_id": job["produto_id"],
            "recebido_em": datetime.fromtimestamp(job["recebido_em"], timezone.utc).isoformat()}
        registro = {k: v for k, v in produto.items() if k in CAMPOS_REMOTOS}
        registro["raw_text"] = job["texto"][:2000]
        dados = await self._executar(self._client.rpc("oferta_legado_registrar", {
            "p_evento": evento, "p_produto": registro, "p_hash": hash_legado,
        }))
        return self._resultado(dados)

    async def legados_prontos(self) -> None:
        dados = await self._executar(self._client.rpc("oferta_legado_pronto", {}))
        if len(dados) != 1 or dados[0].get("status") != "confirmado":
            raise RuntimeError("prontidao_legada_nao_confirmada")

    async def salvar_identificada(self, job: dict, produto: dict, identidade: dict,
                                  janela_horas: float) -> ResultadoOferta:
        evento = {
            "canal_id": job["canal_id"], "msg_id": job["msg_id"],
            "canal_origem": job["remoto_canal"], "data_origem": job["data_origem"],
            "recebido_em": datetime.fromtimestamp(job["recebido_em"], timezone.utc).isoformat(),
            "tem_foto": bool(job["tem_foto"]), "enriquecer": bool(identidade.get("enriquecer")),
        }
        registro = {k: v for k, v in produto.items() if k in CAMPOS_REMOTOS}
        registro.update(raw_text=job["texto"][:2000], dedup_hash=job.get("hash"))
        dados = await self._executar(self._client.rpc("oferta_registrar", {
            "p_evento": evento, "p_produto": registro, "p_identidade": identidade,
            "p_janela_horas": janela_horas,
        }))
        return self._resultado(dados)

    def _resultado(self, dados: list[dict]) -> ResultadoOferta:
        if len(dados) != 1 or dados[0].get("status") not in {
            "novo", "duplicado", "reutilizado", "atualizado", "retomado", "removido", "fundido", "enriquecido", "conflito", "incerto",
        }:
            raise RuntimeError("identidade_resposta_incompleta")
        status = dados[0]["status"]
        return ResultadoOferta(self._id(dados[0]), "duplicado" if status == "reutilizado" else status, self._foto(dados[0]))

    async def enriquecer(self, job: dict, identidade: dict) -> ResultadoOferta:
        return self._resultado(await self._executar(self._client.rpc("oferta_enriquecer", {
            "p_canal_id": job["canal_id"], "p_msg_id": job["msg_id"],
            "p_identidade": identidade,
        })))

    async def confirmar_evento(self, job: dict) -> None:
        dados = await self._executar(self._client.rpc("oferta_confirmar", {
            "p_canal_id": job["canal_id"], "p_msg_id": job["msg_id"],
        }))
        if len(dados) != 1 or dados[0].get("status") != "confirmado":
            raise RuntimeError("evento_sem_confirmacao_remota")

    async def buscar_produto(self, produto_id: int) -> dict | None:
        dados = await self._executar(self._client.rpc("oferta_buscar", {"p_id": produto_id}))
        if not dados:
            return None
        if len(dados) != 1:
            raise RuntimeError("alias_ambiguo")
        self._id(dados[0])
        self._foto(dados[0])
        return dados[0]

    async def vincular_foto(self, produto_id: int, url: str) -> str:
        dados = await self._executar(self._client.rpc("oferta_foto", {"p_id": produto_id, "p_url": url}))
        if len(dados) == 1 and dados[0].get("status") == "remocao_reservada":
            # A compensação remove o objeto conhecido sem reabrir seu vínculo.
            return "removida"
        if len(dados) != 1 or dados[0].get("status") not in {"atualizada", "existente", "removida"}:
            raise RuntimeError("foto_sem_confirmacao")
        return dados[0]["status"]

    async def reservar_remocao(self, url: str) -> bool:
        dados = await self._executar(self._client.rpc("midia_reservar_remocao", {"p_url": url}))
        if len(dados) != 1 or type(dados[0].get("permitido")) is not bool:
            raise RuntimeError("remocao_sem_confirmacao")
        return dados[0]["permitido"]

    async def confirmar_remocao(self, url: str) -> None:
        dados = await self._executar(self._client.rpc("midia_confirmar_remocao", {"p_url": url}))
        if len(dados) != 1 or dados[0].get("status") != "confirmado":
            raise RuntimeError("midia_sem_confirmacao_remota")
