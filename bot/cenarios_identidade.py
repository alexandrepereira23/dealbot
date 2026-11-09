"""Fixtures sintéticas e integrações falsas para testes/simulação da etapa 3.

O repositório abaixo é um modelo EM MEMÓRIA, não implementa isolamento SQL,
expiração ou a política de preços do Postgres. Sua fusão explícita só permite
observar as fronteiras do pipeline; testes SQL independentes são obrigatórios.
Não importa clientes, carrega .env ou abre rede.
"""

import asyncio
import copy
from collections import Counter

from src.modelos import Mensagem
from src.repository import ResultadoOferta


AMAZON = "https://www.amazon.com.br/dp/B012345678"
MERCADO_LIVRE = "https://produto.mercadolivre.com.br/MLB-1234567890"


def contexto_forte(*, ml=False):
    """Provas EXPLÍCITAS da fixture, jamais defaults inferidos de produção."""
    def nao_aplicavel(motivo):
        return {"estado": "nao_aplicavel", "motivo": motivo}

    return {"identidade": {
        "anuncio": "MLB-1234567890" if ml else nao_aplicavel("Sem anúncio adicional nesta fixture"),
        "vendedor": "SELLER1", "sku": "SKU-A", "variante": "preto-128",
        "estado": "novo", "quantidade": 1, "kit": "unitario",
        "elegibilidade": "todos os clientes", "pagamento": "pix",
        "cupom": nao_aplicavel("Declarado explicitamente sem cupom nesta fixture"),
        "restricoes": "explicitamente sem outras restricoes",
        "frete": "gratis para todo Brasil",
        "assinatura": nao_aplicavel("Compra avulsa sem assinatura nesta fixture"),
    }}


def mensagem_sintetica(msg_id=1, canal=-100111, *, url=AMAZON, foto=False,
                       contexto=None, origem="live", preco="99,90"):
    return Mensagem(canal, msg_id, f"sintetico_{abs(canal)}",
                    f"Notebook sintético\nR$ {preco}\n{url}",
                    "2026-11-05T12:00:00+00:00", tem_foto=foto, origem=origem,
                    contexto=contexto_forte() if contexto is None else contexto)


class RepositorioIdentidadeFake:
    """Contrato RPC modelado, sem pretender provar transações reais."""

    def __init__(self, atraso=0):
        self.atraso = atraso
        self.cards = {}
        self.aparicoes = {}
        self.observacoes = {}
        self.aliases = {}
        self.confirmados = set()
        self.reservas = set()
        self.remocoes = set()
        self.chamadas = Counter()
        self.schema_disponivel = True
        self.falha_enriquecer = None
        self.perder_resposta_salvar = False
        self.perder_resposta_enriquecer = False

    async def carregar_filtros(self):
        return []

    async def _operacao(self, nome):
        self.chamadas[nome] += 1
        await asyncio.sleep(self.atraso)
        if not self.schema_disponivel:
            raise RuntimeError("schema_identidade_ausente")

    def canonico(self, produto_id):
        visitados = set()
        while produto_id in self.aliases:
            if produto_id in visitados:
                raise AssertionError("ciclo_no_fake")
            visitados.add(produto_id)
            produto_id = self.aliases[produto_id]
        return produto_id

    @property
    def ativos(self):
        return [c for c in self.cards.values() if c["id"] not in self.aliases and not c["removido"]]

    @staticmethod
    def _equivalente(a, b):
        if a.get("chave") is not None or b.get("chave") is not None:
            # Cópia nunca serve de ponte entre identidades comerciais, nem de
            # evidência para completar uma identidade forte desconhecida.
            return (a.get("chave") is not None and a["chave"] == b.get("chave")
                    and a["componentes"]["comparacao"] == b["componentes"]["comparacao"])
        copia_a, copia_b = a.get("copia") or {}, b.get("copia") or {}
        return (copia_a.get("versao") == copia_b.get("versao") == 1
                and copia_a.get("chave") is not None
                and copia_a["chave"] == copia_b.get("chave")
                and copia_a.get("comparacao") is not None
                and copia_a["comparacao"] == copia_b.get("comparacao"))

    async def salvar_identificada(self, job, produto, identidade, janela_horas):
        await self._operacao("salvar_identificada")
        evento = (job["canal_id"], job["msg_id"])
        if evento in self.aparicoes:
            produto_id = self.canonico(self.aparicoes[evento])
            status = "retomado"
        else:
            existente = next((c for c in self.ativos if self._equivalente(c["identidade"], identidade)), None)
            if existente:
                produto_id, status = existente["id"], "duplicado"
            else:
                produto_id, status = len(self.cards) + 1, "novo"
                self.cards[produto_id] = {**copy.deepcopy(produto), "id": produto_id,
                    "identidade": copy.deepcopy(identidade), "foto_url": None,
                    "removido": False, "janela_horas": janela_horas}
            self.aparicoes[evento] = produto_id
            self.observacoes[evento] = copy.deepcopy(produto)
        if self.perder_resposta_salvar:
            self.perder_resposta_salvar = False
            raise TimeoutError("resposta_fake_perdida_apos_efeito")
        card = self.cards[produto_id]
        return ResultadoOferta(produto_id, "removido" if card["removido"] else status, card["foto_url"])

    async def enriquecer(self, job, identidade):
        await self._operacao("enriquecer")
        if self.falha_enriquecer:
            erro, self.falha_enriquecer = self.falha_enriquecer, None
            raise erro
        produto_id = self.canonico(self.aparicoes[(job["canal_id"], job["msg_id"])])
        fonte = self.cards[produto_id]
        if fonte["removido"]:
            return ResultadoOferta(produto_id, "removido", fonte["foto_url"])
        # Um retry de cópia não pode apagar uma assinatura comercial já forte.
        # Quando há promoção, conservar o JSON inteiro (evidências, comparação,
        # cópia e campos futuros), não reconstruir uma assinatura parcial.
        if fonte["identidade"].get("chave") is None or identidade.get("chave") is not None:
            fonte["identidade"] = copy.deepcopy(identidade)
        equivalentes = [c["id"] for c in self.ativos
                        if c["id"] == produto_id
                        or self._equivalente(c["identidade"], fonte["identidade"])]
        sobrevivente = min(equivalentes)
        for perdedor in equivalentes:
            if perdedor == sobrevivente:
                continue
            self.aliases[perdedor] = sobrevivente
            self.cards[sobrevivente]["foto_url"] = (self.cards[sobrevivente]["foto_url"]
                                                       or self.cards[perdedor]["foto_url"])
            for evento, vinculo in self.aparicoes.items():
                if self.canonico(vinculo) == sobrevivente:
                    self.aparicoes[evento] = sobrevivente
        if self.perder_resposta_enriquecer:
            self.perder_resposta_enriquecer = False
            raise TimeoutError("resposta_fake_perdida_apos_fusao")
        return ResultadoOferta(sobrevivente, "fundido" if len(equivalentes) > 1 else "enriquecido",
                               self.cards[sobrevivente]["foto_url"])

    async def confirmar_evento(self, job):
        await self._operacao("confirmar_evento")
        self.confirmados.add((job["canal_id"], job["msg_id"]))

    async def buscar_produto(self, produto_id):
        await self._operacao("buscar_produto")
        card = self.cards.get(self.canonico(produto_id))
        return copy.deepcopy(card) if card and not card["removido"] else None

    async def vincular_foto(self, produto_id, url):
        await self._operacao("vincular_foto")
        card = self.cards.get(self.canonico(produto_id))
        if not card or card["removido"]:
            return "removida"
        if card["foto_url"] or url in self.reservas:
            return "existente"
        card["foto_url"] = url
        return "atualizada"

    async def reservar_remocao(self, url):
        await self._operacao("reservar_remocao")
        if any(c["foto_url"] == url for c in self.ativos):
            return False
        self.reservas.add(url)
        return True

    async def confirmar_remocao(self, url):
        await self._operacao("confirmar_remocao")
        self.remocoes.add(url)


class ResolvedorFake:
    def __init__(self, destinos=None, *, atraso=0, bloqueado=False, resultado=None):
        self.destinos = destinos or {}
        self.atraso = atraso
        self.resultado = resultado
        self.iniciou = asyncio.Event()
        self.liberar = asyncio.Event()
        if not bloqueado:
            self.liberar.set()
        self.chamadas = []
        self.ativos = self.max_ativos = 0
        self.fechado = False

    async def resolver(self, url):
        self.chamadas.append(url)
        self.ativos += 1
        self.max_ativos = max(self.max_ativos, self.ativos)
        self.iniciou.set()
        try:
            await self.liberar.wait()
            await asyncio.sleep(self.atraso)
            return copy.deepcopy(self.resultado) if self.resultado is not None else {
                "estado": "positivo", "url_final": self.destinos.get(url, AMAZON),
                "motivo": "destino_sintetico", "versao": 2}
        finally:
            self.ativos -= 1

    async def aclose(self):
        self.fechado = True


class StorageFake:
    def __init__(self):
        self.objetos = {}
        self.removidos = []

    async def url_publica(self, chave):
        return "https://storage.invalid/" + chave

    async def enviar(self, chave, dados):
        self.objetos[chave] = dados
        return await self.url_publica(chave)

    async def remover(self, chave):
        self.objetos.pop(chave, None)
        self.removidos.append(chave)


class TelegramFake:
    def __init__(self):
        self.iniciou = asyncio.Event()
        self.liberar = asyncio.Event()
        self.liberar.set()
        self.chamadas = 0

    async def baixar_foto(self, canal_id, msg_id, limite):
        self.chamadas += 1
        self.iniciou.set()
        await self.liberar.wait()
        return b"foto_sintetica"[:limite]


async def linhas(estado, consulta, valores=()):
    """Leitura de diagnóstico pelo mesmo executor serial, sem outra conexão."""
    return await estado._executar(lambda: [dict(r) for r in estado._conexao().execute(consulta, valores)])


async def aguardar(condicao, *, timeout=10, pipeline=None):
    """Espera estado observável; watchdog finito, nunca pressupõe latência fake."""
    async def verificar():
        while not await condicao():
            if pipeline and pipeline.fatal and pipeline.fatal.done():
                raise pipeline.fatal.result()
            await asyncio.sleep(.005)
    await asyncio.wait_for(verificar(), timeout)
