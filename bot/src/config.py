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
    midia_modo: str = "supabase"
    midia_local_dir: Path | None = None
    midia_max_pixels: int = 24000000
    midia_lado_max: int = 960
    midia_saida_max_bytes: int = 358400
    midia_transform_workers: int = 1
    retry_base: float = 1
    retry_max: float = 300
    shutdown_timeout: float = 25
    janela_oferta_horas: float = 48
    enriquecimento_workers: int = 1
    resolucao_timeout: float = 5
    resolucao_redirects: int = 5
    resolucao_max_bytes: int = 65536
    resolucao_tentativas: int = 3
    resolucao_cache_positivo: float = 86400
    resolucao_cache_negativo: float = 900

    def __post_init__(self) -> None:
        for nome, valor in vars(self).items():
            if nome not in {"state_dir", "midia_modo", "midia_local_dir"} and (valor <= 0 or not float(valor) < float("inf")):
                raise ValueError(f"Configuração inválida: {nome} precisa ser positiva e finita")
        if self.midia_modo not in {"supabase", "local"}:
            raise ValueError("BOT_MIDIA_MODO precisa ser supabase ou local")
        if self.midia_modo == "local" and self.midia_local_dir is None:
            raise ValueError("MIDIA_LOCAL_DIR é obrigatório no modo local")
        if self.midia_local_dir is not None and not self.midia_local_dir.is_absolute():
            raise ValueError("MIDIA_LOCAL_DIR precisa ser absoluto")
        if self.midia_local_dir is not None:
            midia = self.midia_local_dir.expanduser().resolve(strict=False)
            estado = self.state_dir.expanduser().resolve(strict=False)
            # A mídia é compartilhada com a API; estado e código não são. Não
            # permitir igualdade, filho ou pai evita expor SQLite/sessões quando
            # o diretório de mídia recebe grupo 2770 na publicação.
            raiz_codigo = Path(__file__).resolve().parents[2]
            if any(self._caminhos_sobrepostos(midia, protegido) for protegido in (estado, raiz_codigo)):
                raise ValueError("MIDIA_LOCAL_DIR deve ser dedicado e não pode sobrepor estado ou código")
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
        for nome, limite in (("enriquecimento_workers", 8), ("resolucao_redirects", 10),
                              ("resolucao_max_bytes", 1048576), ("resolucao_tentativas", 10)):
            if type(getattr(self, nome)) is not int or getattr(self, nome) > limite:
                raise ValueError(f"{nome} deve ser inteiro positivo até {limite}")
        for nome, limite in (("midia_max_pixels", 100000000), ("midia_lado_max", 4096),
                             ("midia_saida_max_bytes", 1048576), ("midia_transform_workers", 4)):
            if type(getattr(self, nome)) is not int or getattr(self, nome) > limite:
                raise ValueError(f"{nome} deve ser inteiro positivo até {limite}")

    @staticmethod
    def _caminhos_sobrepostos(um: Path, outro: Path) -> bool:
        try:
            return Path(os.path.commonpath((str(um), str(outro)))) in (um, outro)
        except ValueError:
            return False

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
             "midia_max_bytes": "MIDIA_MAX_BYTES", "midia_modo": "MIDIA_MODO",
             "midia_max_pixels": "MIDIA_MAX_PIXELS", "midia_lado_max": "MIDIA_LADO_MAX",
             "midia_saida_max_bytes": "MIDIA_SAIDA_MAX_BYTES",
             "midia_transform_workers": "MIDIA_TRANSFORM_WORKERS", "retry_base": "RETRY_BASE_S",
            "retry_max": "RETRY_MAX_S", "shutdown_timeout": "SHUTDOWN_TIMEOUT_S",
            "janela_oferta_horas": "JANELA_OFERTA_HORAS", "enriquecimento_workers": "ENRIQUECIMENTO_WORKERS",
            "resolucao_timeout": "RESOLUCAO_TIMEOUT_S", "resolucao_redirects": "RESOLUCAO_REDIRECTS",
            "resolucao_max_bytes": "RESOLUCAO_MAX_BYTES", "resolucao_tentativas": "RESOLUCAO_TENTATIVAS",
            "resolucao_cache_positivo": "RESOLUCAO_CACHE_POSITIVO_S", "resolucao_cache_negativo": "RESOLUCAO_CACHE_NEGATIVO_S",
        }
        padrao = cls()
        valores = {}
        for nome, env in nomes.items():
            tipo = cls.__annotations__[nome]
            valores[nome] = tipo(os.environ.get(f"BOT_{env}", str(getattr(padrao, nome))))
        valores["state_dir"] = Path(os.environ.get("BOT_STATE_DIR", str(padrao.state_dir))).expanduser()
        diretorio_midia = os.environ.get("MIDIA_LOCAL_DIR")
        valores["midia_local_dir"] = Path(diretorio_midia).expanduser() if diretorio_midia else None
        return cls(**valores)


def obrigatoria(chave: str) -> str:
    """Obtém um segredo apenas na composição da aplicação, sem expor seu valor."""
    valor = os.environ.get(chave)
    if not valor:
        raise RuntimeError(f"Variável de ambiente ausente: {chave}")
    return valor
