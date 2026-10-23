"""Fronteira Telethon 1.36: identidade estável, histórico e mídia limitados."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from .estado import EstadoLocal
from .modelos import ErroPermanente, Mensagem


@dataclass(frozen=True)
class PaginaHistorico:
    """Cobertura inclui tombstones, mas o desempacotamento continua (mensagens, fim)."""

    mensagens: list[Mensagem]
    esgotou: bool
    cursor: int

    def __iter__(self) -> Iterator[list[Mensagem] | bool]:
        yield self.mensagens
        yield self.esgotou


class Telegram:
    """Cliente injetado; referências de canal privadas sobrevivem a StringSession."""

    def __init__(self, client: Any, estado: EstadoLocal, timeout: float = 10) -> None:
        self.client = client
        self.estado = estado
        self.timeout = timeout

    async def resolver(self, username: str) -> dict:
        from telethon import utils
        from telethon.tl.types import Channel

        entidade = await asyncio.wait_for(self.client.get_entity(username), self.timeout)
        if not isinstance(entidade, Channel) or entidade.access_hash is None:
            raise ValueError("destino_nao_e_canal_acessivel")
        return {"canal_id": utils.get_peer_id(entidade), "access_hash": entidade.access_hash,
                "username": entidade.username or username}

    async def _peer(self, canal_id: int) -> Any:
        from telethon import utils
        from telethon.tl.types import InputPeerChannel

        canal = await self.estado.canal(canal_id)
        if canal is None or canal["access_hash"] is None:
            raise RuntimeError("referencia_de_canal_indisponivel")
        real_id, _ = utils.resolve_id(canal_id)
        return InputPeerChannel(real_id, int(canal["access_hash"]))

    @staticmethod
    def envelope(msg: Any, canal_id: int, username: str, origem: str = "historico") -> Mensagem:
        data = getattr(msg, "date", None)
        if data is None:
            raise ValueError("mensagem_sem_data")
        # Preservar a precedência anterior: Telethon .text inclui formatação de
        # entidades (ex.: código de cupom), enquanto .message é texto sem markup.
        texto = getattr(msg, "text", None) or getattr(msg, "message", "") or ""
        return Mensagem(canal_id, msg.id, username, texto, data.isoformat(),
                        bool(getattr(msg, "photo", None)), origem)

    async def mais_nova(self, canal_id: int) -> int:
        mensagens = await asyncio.wait_for(self.client.get_messages(await self._peer(canal_id), limit=1), self.timeout)
        return mensagens[0].id if mensagens else 0

    async def pagina(self, canal: dict, quantidade: int) -> PaginaHistorico:
        """Um GetHistory por página; nunca esconder paginação/retries no iterador."""
        from telethon.tl.functions.messages import GetHistoryRequest
        from telethon.tl.types import Message, MessageEmpty

        tamanho = min(quantidade, 100)
        if tamanho <= 0:
            raise ValueError("tamanho_de_pagina_invalido")
        peer = await self._peer(canal["canal_id"])
        atual = await self.estado.canal(canal["canal_id"])
        if not atual or not atual["ativo"] or atual["geracao"] != canal["geracao"]:
            return PaginaHistorico([], False, canal["cursor"])
        inicio = datetime.fromtimestamp(canal["bootstrap"], timezone.utc) if canal["cursor"] == 0 else None
        # Mesmos offsets crescentes de _MessagesIter._init no Telethon 1.36:
        # offset_date só no bootstrap; offset_id exclusivo + add_offset=-limit.
        # min_id/max_id são aplicados localmente: o próprio SDK evita enviá-los
        # porque o Telegram pode devolver vazio incorretamente perto da fronteira.
        pedido = GetHistoryRequest(peer=peer, offset_id=canal["cursor"] + 1 if canal["cursor"] else 0,
            offset_date=inicio, add_offset=-tamanho, limit=tamanho, min_id=0, max_id=0, hash=0)
        resposta = await asyncio.wait_for(self.client(pedido), self.timeout)
        registros = getattr(resposta, "messages", None)
        if not isinstance(registros, (list, tuple)) or len(registros) > tamanho:
            raise ValueError("resposta_historico_invalida")
        if not registros:
            return PaginaHistorico([], True, canal["limite"])
        ids = [getattr(msg, "id", None) for msg in registros]
        if any(type(i) is not int or i <= canal["cursor"] for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("pagina_fora_da_cobertura")
        cursor = min(max(ids), canal["limite"])
        mensagens = []
        for msg in sorted(registros, key=lambda m: m.id):
            if msg.id > canal["limite"] or isinstance(msg, MessageEmpty):
                continue
            # Tombstones só comprovam cobertura; não inventar texto/data/evento.
            # O offset por data é reforçado localmente no primeiro bootstrap.
            if inicio is not None and msg.date is not None and msg.date < inicio:
                continue
            envelope = self.envelope(msg, canal["canal_id"], canal["username"])
            # Respostas raw não passam por _finish_init do iterador. Preservar
            # .text formatado usando o parse_mode público, sem aquele helper privado.
            modo = getattr(self.client, "parse_mode", None)
            if isinstance(msg, Message) and modo is not None:
                envelope = replace(envelope, texto=modo.unparse(msg.message or "", msg.entities or []))
            mensagens.append(envelope)
        # Resposta curta não é fim. Só o trecho retornado (incluindo tombstones)
        # avança; a próxima RPC acontece DEPOIS do commit/pacing desta página.
        return PaginaHistorico(mensagens, cursor == canal["limite"], cursor)

    async def saudavel(self) -> bool:
        """RPC real (não cache de get_me) detecta reconexões lógicas não sinalizadas."""
        from telethon.tl.functions import PingRequest

        if not self.client.is_connected():
            await asyncio.wait_for(self.client.connect(), self.timeout)
        resposta = await asyncio.wait_for(self.client(PingRequest(ping_id=1)), self.timeout)
        return resposta is not None

    async def baixar_foto(self, canal_id: int, msg_id: int, max_bytes: int) -> bytes | None:
        peer = await self._peer(canal_id)
        msg = await asyncio.wait_for(self.client.get_messages(peer, ids=msg_id), self.timeout)
        if msg is None:
            raise ErroPermanente("mensagem_apagada")
        if not getattr(msg, "photo", None):
            return None
        # iter_download permite impor teto DURANTE a transferência, sem arquivo síncrono.
        foto = msg.photo
        tamanhos = [getattr(t, "size", 0) or max(getattr(t, "sizes", []) or [0])
                    for t in getattr(foto, "sizes", [])]
        if tamanhos and max(tamanhos) > max_bytes:
            raise ErroPermanente("midia_excede_limite")
        dados = bytearray()
        iterador = self.client.iter_download(msg.media, request_size=64 * 1024)
        try:
            async for bloco in iterador:
                if len(dados) + len(bloco) > max_bytes:
                    raise ErroPermanente("midia_excede_limite")
                dados.extend(bloco)
        except Exception as erro:
            if type(erro).__name__ not in {"FileReferenceExpiredError", "FileReferenceInvalidError"}:
                raise
            # Um retry refaz get_messages e obtém file_reference novo.
            raise AcessoMidiaExpirado() from erro
        finally:
            # Telethon devolve o sender emprestado em close, inclusive em timeout.
            fechar = getattr(iterador, "close", None) or getattr(iterador, "aclose", None)
            if fechar is not None:
                await asyncio.shield(fechar())
        return bytes(dados)


class AcessoMidiaExpirado(RuntimeError):
    """Referência será renovada no próximo refetch; não é perda permanente da oferta."""
