"""Configuração explícita; importar módulos não lê segredos nem abre clientes."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Limites locais e intervalos em segundos, carregados apenas no startup."""

    state_dir: Path = Path.home() / ".local" / "state" / "dealbot"
    retencao_dias: float = 7
    limpeza_intervalo: float = 3600
    limpeza_lote: int = 100
    limpeza_max_lotes: int = 10
    limpeza_continuacao: float = 1
    oferta_workers: int = 4
    midia_workers: int = 1
    io_workers: int = 1
    buffer_max: int = 100
    filtros_intervalo: float = 15
    canais_intervalo: float = 30
    recuperacao_intervalo: float = 60
    recuperacao_pausa: float = 0.25
    bootstrap_horas: float = 24
    recuperacao_lote: int = 100
    prioridade_live_cota: int = 4
    rede_timeout: float = 10
    midia_timeout: float = 30
    midia_max_bytes: int = 10485760
    retry_base: float = 1
    retry_max: float = 300
    shutdown_timeout: float = 25

    def __post_init__(self) -> None:
        for nome, valor in vars(self).items():
            if nome != "state_dir" and (valor <= 0 or not float(valor) < float("inf")):
                raise ValueError(f"Configuração inválida: {nome} precisa ser positiva e finita")
        if self.recuperacao_lote > self.buffer_max:
            raise ValueError("BOT_RECUPERACAO_LOTE não pode exceder BOT_BUFFER_MAX")
        if self.retry_max < self.retry_base:
            raise ValueError("BOT_RETRY_MAX_S precisa ser >= BOT_RETRY_BASE_S")
        if self.io_workers != 1:
            raise ValueError("BOT_IO_WORKERS precisa ser 1: conexão SQLite tem afinidade de thread")
        for nome, limite in (("limpeza_lote", 1000), ("limpeza_max_lotes", 100)):
            valor = getattr(self, nome)
            if type(valor) is not int or valor > limite:
                raise ValueError(f"{nome} precisa ser inteiro e não pode exceder {limite}")
        if self.limpeza_continuacao > 60:
            raise ValueError("BOT_LIMPEZA_CONTINUACAO_S não pode exceder 60")

    @classmethod
    def carregar(cls) -> "Config":
        """Lê tuning sem carregar .env (responsabilidade da entrada principal)."""
        nomes = {
            "retencao_dias": "RETENCAO_DIAS", "limpeza_intervalo": "LIMPEZA_INTERVALO_S",
            "limpeza_lote": "LIMPEZA_LOTE", "limpeza_max_lotes": "LIMPEZA_MAX_LOTES",
            "limpeza_continuacao": "LIMPEZA_CONTINUACAO_S",
            "oferta_workers": "OFERTA_WORKERS", "midia_workers": "MIDIA_WORKERS",
            "io_workers": "IO_WORKERS", "buffer_max": "BUFFER_MAX",
            "filtros_intervalo": "FILTROS_INTERVALO_S", "canais_intervalo": "CANAIS_INTERVALO_S",
            "recuperacao_intervalo": "RECUPERACAO_INTERVALO_S", "bootstrap_horas": "BOOTSTRAP_HORAS",
            "recuperacao_pausa": "RECUPERACAO_PAUSA_S",
            "recuperacao_lote": "RECUPERACAO_LOTE", "prioridade_live_cota": "PRIORIDADE_LIVE_COTA",
            "rede_timeout": "REDE_TIMEOUT_S", "midia_timeout": "MIDIA_TIMEOUT_S",
            "midia_max_bytes": "MIDIA_MAX_BYTES", "retry_base": "RETRY_BASE_S",
            "retry_max": "RETRY_MAX_S", "shutdown_timeout": "SHUTDOWN_TIMEOUT_S",
        }
        padrao = cls()
        valores = {}
        for nome, env in nomes.items():
            tipo = cls.__annotations__[nome]
            valores[nome] = tipo(os.environ.get(f"BOT_{env}", str(getattr(padrao, nome))))
        valores["state_dir"] = Path(os.environ.get("BOT_STATE_DIR", str(padrao.state_dir))).expanduser()
        return cls(**valores)


def obrigatoria(chave: str) -> str:
    """Obtém um segredo apenas na composição da aplicação, sem expor seu valor."""
    valor = os.environ.get(chave)
    if not valor:
        raise RuntimeError(f"Variável de ambiente ausente: {chave}")
    return valor
