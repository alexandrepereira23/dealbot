"""Prévia offline: ``python -m previa --mensagem texto.txt --filtros filtros.json``."""

import argparse
import json
import sys
from pathlib import Path

from src.avaliacao import avaliar_mensagem
from src.filters import preparar_filtros


def validar_contexto(contexto: object, tamanho: int) -> dict:
    """Valida o formato público da prévia antes da avaliação, sem SDK ou rede."""
    if not isinstance(contexto, dict) or contexto.get("versao", 1) != 1:
        raise ValueError("contexto_invalido")
    if "canal_id" in contexto and type(contexto["canal_id"]) is not int:
        raise ValueError("contexto_invalido")
    if "username" in contexto and not isinstance(contexto["username"], str):
        raise ValueError("contexto_invalido")
    for campo in ("links", "codigos", "exclusoes"):
        valores = contexto.get(campo, [])
        if not isinstance(valores, list):
            raise ValueError("contexto_invalido")
        for valor in valores:
            if not isinstance(valor, dict):
                raise ValueError("contexto_invalido")
            if campo == "links" and (not isinstance(valor.get("url"), str)
                    or valor.get("origem") not in ("entidade", "botao")
                    or not isinstance(valor.get("rotulo", ""), str)):
                raise ValueError("contexto_invalido")
            if campo != "links" or "offset" in valor or "length" in valor:
                inicio, comprimento = valor.get("offset"), valor.get("length")
                if (type(inicio) is not int or type(comprimento) is not int
                        or inicio < 0 or comprimento < 0 or inicio + comprimento > tamanho):
                    raise ValueError("contexto_invalido")
    return contexto


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extrai e avalia mensagem local, sem tokens ou rede.")
    parser.add_argument("--mensagem", type=Path, required=True)
    parser.add_argument("--filtros", type=Path, required=True)
    parser.add_argument("--contexto", type=Path)
    args = parser.parse_args(argv)
    try:
        texto = args.mensagem.read_text(encoding="utf-8-sig")
        filtros = preparar_filtros(json.loads(args.filtros.read_text(encoding="utf-8-sig")))
        contexto = validar_contexto(json.loads(args.contexto.read_text(encoding="utf-8-sig")), len(texto)) if args.contexto else {}
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({"erro": "entrada_ou_configuracao_invalida"}), file=sys.stderr)
        return 2
    try:
        resultado = avaliar_mensagem(texto, filtros, contexto,
            canal_id=contexto.get("canal_id"), username=contexto.get("username", ""))
        print(json.dumps({"produto": resultado.extracao.produto, "conteudo": resultado.extracao.conteudo,
                          "aceita": resultado.aceita, "diagnostico": resultado.diagnostico},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        # Prévia deliberadamente exibe dados fornecidos pelo operador; falhas
        # técnicas, porém, não serializam payload de exceção/segredos acidentais.
        print(json.dumps({"erro": "falha_tecnica"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
