"""Persistência assíncrona e reconciliação dos efeitos remotos da oferta."""

import asyncio
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .dedup import gerar_hash
from .modelos import ErroPermanente, normalizar_username
from .observabilidade import log
from .politica import configurar_limites_http


JANELA_DEDUP_HORAS = 48
QUANTIDADE_TRAVAS = 128


@dataclass(frozen=True)
class ResultadoOferta:
    produto_id: int
    status: str  # novo, duplicado ou retomado
    foto_url: str | None


class RepositorioSupabase:
    def __init__(self, client: Any, timeout: float = 10) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("O timeout do repositório deve ser positivo e finito")
        self._client = client
        self._timeout = timeout
        configurar_limites_http(getattr(getattr(client, "postgrest", None), "session", None))
        # Quantidade fixa: o consumo não cresce com a quantidade de ofertas.
        # Uma instância compartilhada pelos workers; não é lock distribuído.
        self._travas = tuple(asyncio.Lock() for _ in range(QUANTIDADE_TRAVAS))

    async def _executar(self, consulta: Any) -> list[dict]:
        inicio = time.monotonic()
        try:
            resposta = await asyncio.wait_for(consulta.execute(), timeout=self._timeout)
        finally:
            log("supabase_operacao", duracao_ms=round((time.monotonic() - inicio) * 1000, 2))
        dados = getattr(resposta, "data", None)
        if not isinstance(dados, list) or any(not isinstance(item, dict) for item in dados):
            raise RuntimeError("Resposta incompleta do Supabase: lista de registros ausente")
        return dados

    @staticmethod
    def _id(registro: dict, campo: str = "id") -> int:
        valor = registro.get(campo)
        if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
            raise RuntimeError("Resposta incompleta do Supabase: identificador inválido")
        return valor

    @staticmethod
    def _foto(registro: dict) -> str | None:
        if "foto_url" not in registro or (
            registro["foto_url"] is not None and not isinstance(registro["foto_url"], str)
        ):
            raise RuntimeError("Resposta incompleta do Supabase: foto ausente ou inválida")
        return registro["foto_url"]

    @staticmethod
    def _aliases(canal: str, aliases: list[str]) -> list[str]:
        chaves: list[str] = []
        for alias in [canal, *aliases]:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("Alias remoto deve ser textual e não vazio")
            nome = alias.strip().lstrip("@")
            for variante in (alias.strip(), nome, "@" + nome, nome.lower(), "@" + nome.lower()):
                if variante not in chaves:
                    chaves.append(variante)
        return chaves

    async def carregar_filtros(self) -> list[dict]:
        return await self._executar(
            self._client.table("filtros").select("*").eq("ativo", True)
        )

    async def listar_canais(self) -> list[str]:
        dados = await self._executar(
            self._client.table("canais").select("username").eq("ativo", True)
        )
        if any(not isinstance(item.get("username"), str) or not item["username"].strip() for item in dados):
            raise RuntimeError("Resposta incompleta do Supabase: username inválido")
        return [item["username"] for item in dados]

    async def buscar_produto(self, produto_id: int) -> dict | None:
        dados = await self._executar(
            self._client.table("produtos").select("*").eq("id", produto_id).limit(1)
        )
        if not dados:
            return None
        self._id(dados[0])
        self._foto(dados[0])
        return dados[0]

    async def _reconciliar(self, msg_id: int, aliases: list[str]) -> tuple[dict, str] | None:
        # Não há janela temporal aqui: um retry tardio ainda é o mesmo evento.
        # Comparação case-insensitive preserva grafias legadas desconhecidas sem
        # trocar sua chave remota. Underscore é literal, não wildcard de ILIKE.
        if any(not re.fullmatch(r"@?[A-Za-z0-9_-]+", alias) for alias in aliases):
            raise ValueError("Alias remoto contém caracteres inválidos")
        padroes = sorted({alias.lower().replace("_", "\\_") for alias in aliases})
        filtro = ",".join("canal_origem.ilike." + padrao for padrao in padroes)
        produtos = await self._executar(
            self._client.table("produtos").select("*")
            .eq("telegram_msg_id", msg_id).or_(filtro)
        )
        aparicoes = await self._executar(
            self._client.table("produto_aparicoes").select("produto_id,canal_origem")
            .eq("telegram_msg_id", msg_id).or_(filtro)
        )
        ids = {self._id(item) for item in produtos}
        ids.update(self._id(item, "produto_id") for item in aparicoes)
        if not ids:
            return None
        if len(ids) != 1:
            raise RuntimeError("Aliases do evento apontam para produtos remotos conflitantes")
        produto_id = ids.pop()
        produto = produtos[0] if produtos else await self.buscar_produto(produto_id)
        if produto is None:
            raise RuntimeError("Produto da aparição não encontrado durante reconciliação")
        self._foto(produto)
        # A chave de uma aparição anterior tem prioridade: nunca criar variante.
        canal = (aparicoes or produtos)[0].get("canal_origem")
        if not isinstance(canal, str) or not canal:
            raise RuntimeError("Resposta incompleta do Supabase: chave remota ausente")
        return produto, canal

    async def _registrar_aparicao(self, produto_id: int, canal: str, msg_id: int) -> None:
        dados = await self._executar(
            self._client.table("produto_aparicoes").upsert(
                {"produto_id": produto_id, "canal_origem": canal, "telegram_msg_id": msg_id},
                on_conflict="canal_origem,telegram_msg_id", ignore_duplicates=True,
            )
        )
        if not dados:
            dados = await self._executar(
                self._client.table("produto_aparicoes").select("produto_id")
                .eq("canal_origem", canal).eq("telegram_msg_id", msg_id).limit(1)
            )
        if not dados or self._id(dados[0], "produto_id") != produto_id:
            raise RuntimeError("Aparição remota não confirmada para o produto esperado")

    @staticmethod
    def _status_retomada(produto: dict, msg_id: int, aliases: list[str]) -> str:
        """Reconstitui a decisão pela origem já persistida, sem mudar identidade.

        A oferta criada por este evento continua uma aprovação retomada. Um
        evento que apenas referencia a oferta de outra mensagem/canal continua
        duplicata, inclusive depois de falha de aparição ou reinício.
        """
        origem = produto.get("canal_origem")
        mesmo_evento = (produto.get("telegram_msg_id") == msg_id
            and isinstance(origem, str)
            and normalizar_username(origem) in {normalizar_username(a) for a in aliases})
        return "retomado" if mesmo_evento else "duplicado"

    async def salvar_oferta(self, registro: dict, aliases: list[str],
                            produto_id: int | None = None, ao_vincular: Any = None) -> ResultadoOferta:
        canal = registro.get("canal_origem")
        msg_id = registro.get("telegram_msg_id")
        if not isinstance(canal, str) or not canal.strip():
            raise ValueError("A oferta precisa de uma chave remota textual")
        if not isinstance(msg_id, int) or isinstance(msg_id, bool) or msg_id <= 0:
            raise ValueError("A oferta precisa de um identificador de mensagem válido")
        chaves = self._aliases(canal, aliases)
        hash_oferta = gerar_hash(registro)
        trava = self._travas[int(hash_oferta, 16) % QUANTIDADE_TRAVAS]
        async with trava:
            if produto_id is not None:
                produto_vinculado = await self.buscar_produto(produto_id)
                if produto_vinculado is None:
                    raise ErroPermanente("produto_vinculado_removido")
                existente = await self._reconciliar(msg_id, chaves)
                if existente is not None and self._id(existente[0]) != produto_id:
                    raise RuntimeError("Vínculo persistido conflita com aparição remota")
                chave = existente[1] if existente else canal
                await self._registrar_aparicao(produto_id, chave, msg_id)
                return ResultadoOferta(produto_id, self._status_retomada(produto_vinculado, msg_id, chaves),
                                       self._foto(produto_vinculado))
            existente = await self._reconciliar(msg_id, chaves)
            if existente is not None:
                produto, chave = existente
                if ao_vincular is not None:
                    await ao_vincular(self._id(produto))
                await self._registrar_aparicao(self._id(produto), chave, msg_id)
                return ResultadoOferta(self._id(produto), self._status_retomada(produto, msg_id, chaves),
                                       self._foto(produto))

            desde = (datetime.now(timezone.utc) - timedelta(hours=JANELA_DEDUP_HORAS)).isoformat()
            duplicatas = await self._executar(
                self._client.table("produtos").select("*").eq("dedup_hash", hash_oferta)
                .gte("criado_em", desde).order("criado_em", desc=True).limit(1)
            )
            if duplicatas:
                produto = duplicatas[0]
                if ao_vincular is not None:
                    await ao_vincular(self._id(produto))
                await self._registrar_aparicao(self._id(produto), canal, msg_id)
                return ResultadoOferta(self._id(produto), "duplicado", self._foto(produto))

            registro_final = {**registro, "dedup_hash": hash_oferta}
            if isinstance(registro_final.get("raw_text"), str):
                registro_final["raw_text"] = registro_final["raw_text"][:2000]
            # ON CONFLICT DO NOTHING não altera foto, criado_em nem outros dados.
            # Timeout após commit propaga: o próximo retry reconcilia pelo evento.
            inseridos = await self._executar(
                self._client.table("produtos").upsert(
                    registro_final, on_conflict="canal_origem,telegram_msg_id",
                    ignore_duplicates=True,
                )
            )
            if inseridos:
                produto, chave, status = inseridos[0], canal, "novo"
            else:
                existente = await self._reconciliar(msg_id, chaves)
                if existente is None:
                    raise RuntimeError("Gravação da oferta sem confirmação do identificador remoto")
                produto, chave = existente
                status = self._status_retomada(produto, msg_id, chaves)
            produto_id = self._id(produto)
            foto = self._foto(produto)
            if ao_vincular is not None:
                await ao_vincular(produto_id)
            await self._registrar_aparicao(produto_id, chave, msg_id)
            return ResultadoOferta(produto_id, status, foto)

    async def vincular_foto(self, produto_id: int, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("A URL da foto não pode ser vazia")
        produto = await self.buscar_produto(produto_id)
        if produto is None:
            return "removida"
        if self._foto(produto) is not None:
            return "existente"
        # Compare-and-set evita sobrescrever foto gravada durante esta operação.
        dados = await self._executar(
            self._client.table("produtos").update({"foto_url": url})
            .eq("id", produto_id).is_("foto_url", "null")
        )
        if dados:
            if self._id(dados[0]) != produto_id or self._foto(dados[0]) != url:
                raise RuntimeError("Atualização da foto sem confirmação remota coerente")
            return "atualizada"
        produto = await self.buscar_produto(produto_id)
        if produto is None:
            return "removida"
        if self._foto(produto) is not None:
            return "existente"
        raise RuntimeError("Atualização da foto não confirmada pelo Supabase")
