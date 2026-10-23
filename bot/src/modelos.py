"""Contratos locais sem clientes de rede ou configuração global."""

import time
from dataclasses import dataclass, field


def normalizar_username(username: str) -> str:
    """Normaliza apenas o endereço do canal, não a identidade de ofertas."""
    return username.strip().lstrip("@").lower()


@dataclass(frozen=True)
class Mensagem:
    """Envelope mínimo persistido antes de executar extração ou rede remota."""

    canal_id: int
    msg_id: int
    username: str
    texto: str
    data_origem: str
    tem_foto: bool = False
    origem: str = "live"
    recebido_em: float = field(default_factory=time.time)


class FalhaLocal(RuntimeError):
    """Estado durável indisponível: parar a coleta, nunca fingir aceitação."""


class ErroPermanente(RuntimeError):
    """Dado/mídia irrecuperável; a oferta já salva não é afetada."""


class Aguardar(RuntimeError):
    """Espera recuperável conhecida, como FloodWait ou Retry-After."""

    def __init__(self, segundos: float, motivo: str = "limite_remoto") -> None:
        super().__init__(motivo)
        self.segundos = segundos


class ErroHTTPRemoto(RuntimeError):
    """Erro saneado fora de HTTPError, para não ser recapturado pelos SDKs."""

    def __init__(self, status: int, espera: float, codigo: str | None = None) -> None:
        super().__init__(f"http_{status}")
        self.status_code = status
        self.seconds = espera
        self.code = codigo
