"""Ponte JSON exclusivamente sintética para QA local; nunca compõe clientes reais."""

import asyncio
import io
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from cenarios_identidade import RepositorioIdentidadeFake, ResolvedorFake
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.midia import ArmazenamentoLocal, ArmazenamentosMidia
from src.modelos import Mensagem
from src.pipeline_identidade import PipelineIdentidade


class StorageProibido:
    def __getattr__(self, nome):
        raise AssertionError("laboratorio_nao_pode_acessar_storage")


class TelegramSintetico:
    def __init__(self):
        self.fontes = {}
        self.portoes = {}

    async def baixar_foto(self, canal, msg, limite):
        await self.portoes[msg].wait()
        return self.fontes[msg]


async def executar(raiz: Path) -> None:
    estado = EstadoLocal(raiz / "estado")
    await estado.abrir()
    repo = RepositorioIdentidadeFake()
    telegram = TelegramSintetico()
    local = ArmazenamentoLocal(raiz / "media", max_entrada=10485760,
        max_pixels=24000000, lado_max=960, max_saida=358400)
    await local.preparar()
    cache = CacheFiltros(repo)
    await cache.atualizar()
    config = replace(Config(), state_dir=raiz / "estado", midia_local_dir=raiz / "media",
        midia_modo="local", retry_base=.05, retry_max=.2)
    pipeline = PipelineIdentidade(estado, repo, ArmazenamentosMidia(StorageProibido(), local),
        telegram, cache, config, resolvedor=ResolvedorFake())
    worker = asyncio.create_task(pipeline._worker("midia"))
    numero = 0

    def snapshot():
        return [{**card, "estado_oferta": "ativa", "identidade_versao": 2,
            "expira_em": card.get("expira_em", "2035-01-01T00:00:00Z"),
            "canonico_id": repo.aliases.get(card["id"]),
            "produto_aparicoes": card.get("produto_aparicoes") or [{"canal_origem": f"canal_{abs(canal)}", "visto_em": "2026-11-10T00:00:00Z"}
                for (canal, _), produto in repo.aparicoes.items() if repo.canonico(produto) == card["id"]]}
            for card in repo.ativos if card.get("expira_em", "2035") > datetime.now(timezone.utc).isoformat()]

    try:
        while linha := await asyncio.to_thread(sys.stdin.readline):
            pedido = json.loads(linha)
            acao = pedido["acao"]
            try:
                if acao == "oferta":
                    numero += 1
                    foto = pedido.get("foto", False)
                    if foto:
                        imagem = Image.new("RGB", tuple(pedido.get("tamanho", [600, 300])), "#2277aa")
                        dados = io.BytesIO()
                        imagem.save(dados, format="JPEG")
                        telegram.fontes[numero] = dados.getvalue()
                        telegram.portoes[numero] = asyncio.Event()
                    agora = datetime.now(timezone.utc).isoformat()
                    msg = Mensagem(-100111, numero, "laboratorio", f"Produto sintetico {numero}\nR$ 99,90\nUse o cupom: LAB10\nhttps://loja.invalid/item/{numero}", agora, foto)
                    await estado.registrar(msg)
                    await pipeline._oferta(await estado.obter_oferta(time.time(), True))
                    evento = await estado.evento(-100111, numero)
                    card = repo.cards[evento["produto_id"]]
                    card.update(criado_em=agora, data_oferta=agora)
                    resposta = {"id": card["id"], "msg": numero}
                elif acao == "liberar":
                    msg = pedido["msg"]
                    if pedido.get("falhar"):
                        telegram.fontes[msg] = b"imagem-invalida"
                    telegram.portoes[msg].set()
                    async def concluir():
                        while True:
                            job = await estado.midia(repo.aparicoes[(-100111, msg)])
                            if job["estado"] in {"pronta", "sem_foto", "falha_permanente", "removida"}:
                                return job["estado"]
                            await asyncio.sleep(.01)
                    resposta = {"estado": await asyncio.wait_for(concluir(), 10)}
                elif acao == "mudar":
                    repo.cards[pedido["id"]].update(pedido["campos"])
                    resposta = {}
                elif acao == "fundir":
                    repo.aliases[pedido["perdedor"]] = pedido["sobrevivente"]
                    resposta = {}
                elif acao == "aparicao":
                    repo.aparicoes[(-100222, numero + 1000)] = pedido["id"]
                    resposta = {}
                elif acao == "snapshot":
                    resposta = {}
                elif acao == "encerrar":
                    break
                else:
                    raise ValueError("acao_de_laboratorio_invalida")
                print(json.dumps({**resposta, "produtos": snapshot(), "disponivel_em": time.time() * 1000}), flush=True)
            except Exception as erro:
                print(json.dumps({"erro": type(erro).__name__}), flush=True)
    finally:
        pipeline.parando = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await pipeline.encerrar()
        await local.fechar()
        await estado.fechar()


if __name__ == "__main__":
    raiz = Path(sys.argv[1])
    if not raiz.is_absolute() or (raiz / "estado").exists():
        raise SystemExit("Diretório absoluto exclusivo de laboratório necessário")
    asyncio.run(executar(raiz))
