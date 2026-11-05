"""Orquestração pura reutilizada por workers e prévia, sem clientes ou ambiente."""

from dataclasses import dataclass

from .extractor import ResultadoExtracao, extrair_detalhado
from .filters import RegraPreparada, avaliar_produto


@dataclass(frozen=True)
class ResultadoMensagem:
    """Extração transitória e diagnóstico compacto, separado do produto remoto."""

    extracao: ResultadoExtracao
    aceita: bool
    diagnostico: dict


def avaliar_mensagem(texto: str, filtros: tuple[RegraPreparada, ...],
                     contexto: dict | None = None, *, canal_id: int | None = None,
                     username: str = "") -> ResultadoMensagem:
    """Usa somente o contexto local e um snapshot já validado/preparado."""
    extracao = extrair_detalhado(texto, contexto, canal_id=canal_id, username=username)
    diagnostico = {"versao": 1, "extracao": list(extracao.motivos),
                   "fonte_preco": extracao.fonte_preco, "fonte_link": extracao.fonte_link}
    if extracao.produto is None:
        motivo = next((m for m in ("multiplas_ofertas", "preco_ambiguo", "sem_evidencia_de_oferta")
                       if m in extracao.motivos), "sem_evidencia_de_oferta")
        diagnostico.update(aceita=False, motivo=motivo,
                           regra=None, por_regra=[])
        return ResultadoMensagem(extracao, False, diagnostico)
    avaliacao = avaliar_produto(extracao.produto, filtros, conteudo=extracao.conteudo, normalizado=True)
    diagnostico.update(avaliacao.como_dict())
    return ResultadoMensagem(extracao, avaliacao.aceita, diagnostico)
