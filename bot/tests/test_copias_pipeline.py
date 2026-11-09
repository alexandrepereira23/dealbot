"""Regressões pelo adaptador real; SQLite real e remoto explicitamente fake.

Nenhum fluxo positivo fabrica contexto.identidade. As mensagens e metadados
Telethon são sintéticos; estes testes NÃO provam transações/concorrência SQL,
janela de validade ou política de preço do PostgreSQL.
"""

import asyncio
import copy
import importlib.util
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

TEM_TELETHON = importlib.util.find_spec("telethon") is not None
if TEM_TELETHON:
    from telethon.tl.types import (
        KeyboardButtonRow, KeyboardButtonUrl, Message, MessageEntityTextUrl,
        PeerChannel, ReplyInlineMarkup,
    )

from cenarios_identidade import (
    AMAZON, MERCADO_LIVRE, RepositorioIdentidadeFake, ResolvedorFake,
    StorageFake, TelegramFake, aguardar, linhas,
)
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.pipeline_identidade import PipelineIdentidade
from src.telegram import Telegram


DESTINO = AMAZON + "?smid=SELLER1"
POST = "Notebook 16 GB\nPor R$ 2.499,90 no Pix"


@unittest.skipUnless(TEM_TELETHON, "Instale requirements para contratos do adaptador Telegram")
class TestCopiasPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="copias-pipeline-")
        self.diretorio = Path(self.tmp.name)
        self.config = replace(Config(), state_dir=self.diretorio, oferta_workers=2,
                              retry_base=.01, retry_max=.02, shutdown_timeout=.05,
                              resolucao_timeout=10)
        self.repo = RepositorioIdentidadeFake()
        self.storage = StorageFake()
        self.telegram = TelegramFake()
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.resolvedor = ResolvedorFake()
        self.pipeline = self.criar_pipeline()
        self.sequencia = 0

    def criar_pipeline(self):
        return PipelineIdentidade(self.estado, self.repo, self.storage, self.telegram,
                                  self.cache, self.config, resolvedor=self.resolvedor)

    async def asyncTearDown(self):
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def reiniciar(self):
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.resolvedor = ResolvedorFake()
        self.pipeline = self.criar_pipeline()

    def mensagem(self, canal, url=DESTINO, *, post=POST, modo="texto",
                 rotulo="Comprar agora", extra_texto="", outros_botoes=(), outros_ocultos=()):
        self.sequencia += 1
        texto = post + "\n" + (url if modo == "texto" else rotulo if modo == "entidade" else "")
        texto += extra_texto
        entidades, botoes = [], list(outros_botoes)
        if modo == "entidade":
            inicio = len((post + "\n").encode("utf-16-le")) // 2
            entidades = [MessageEntityTextUrl(inicio, len(rotulo.encode("utf-16-le")) // 2, url)]
        elif modo == "botao":
            botoes.insert(0, KeyboardButtonUrl(rotulo, url))
        for outro_rotulo, outra_url in outros_ocultos:
            inicio = len((texto + "\n").encode("utf-16-le")) // 2
            texto += "\n" + outro_rotulo
            entidades.append(MessageEntityTextUrl(inicio, len(outro_rotulo.encode("utf-16-le")) // 2, outra_url))
        msg = Message(id=self.sequencia, peer_id=PeerChannel(abs(canal)),
                      date=datetime(2026, 11, 5, 12, tzinfo=timezone.utc),
                      message=texto, entities=entidades,
                      reply_markup=ReplyInlineMarkup([KeyboardButtonRow(botoes)]) if botoes else None)
        mensagem = Telegram.envelope(msg, canal, f"sintetico_{abs(canal)}", "live")
        self.assertNotIn("identidade", mensagem.contexto)
        return mensagem

    async def processar(self, mensagem):
        await self.estado.registrar(mensagem)
        job = await self.estado.obter_oferta(time.time(), True)
        self.assertIsNotNone(job)
        await self.pipeline._oferta(job)
        evento = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
        self.assertIn(evento["estado"], {"aprovada", "duplicata"})
        self.assertIsNotNone(evento["disponibilizado_em"])
        return evento

    async def enriquecimentos_finalizados(self):
        return not await linhas(self.estado, "SELECT 1 FROM enriquecimentos WHERE finalizado_em IS NULL")

    async def finalizada(self, mensagem):
        evento = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
        return bool(evento and evento["finalizado_em"])

    def assert_copia_sem_forte(self, evento):
        identidade = json.loads(evento["identidade"])
        self.assertEqual(identidade["versao"], 2)
        self.assertIsNone(identidade["chave"])
        self.assertEqual(identidade["copia"]["versao"], 1)
        self.assertRegex(identidade["copia"]["chave"], r"^[0-9a-f]{64}$")
        self.assertIsInstance(identidade["copia"]["comparacao"], dict)
        return identidade

    async def assert_par_separado(self, primeira, segunda):
        a, b = await self.processar(primeira), await self.processar(segunda)
        self.assertNotEqual(a["produto_id"], b["produto_id"])
        self.assertNotEqual(self.repo.canonico(a["produto_id"]), self.repo.canonico(b["produto_id"]))
        for evento, mensagem in ((a, primeira), (b, segunda)):
            self.assertIsNone(json.loads(evento["identidade"])["chave"])
            self.assertEqual(self.repo.observacoes[(mensagem.canal_id, mensagem.msg_id)]["link"],
                             json.loads(evento["decisao"])["link"])
        return a, b

    async def test_ml_mesmo_link_um_card_duas_aparicoes_sem_rede(self):
        for canal in (-100111, -100222):
            evento = await self.processar(self.mensagem(canal, MERCADO_LIVRE))
            self.assert_copia_sem_forte(evento)
            self.assertEqual(json.loads(evento["decisao"])["link"], MERCADO_LIVRE)
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(len(self.repo.observacoes), 2)
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(await linhas(self.estado, "SELECT * FROM enriquecimentos"), [])

    async def test_amazon_so_tag_diferente_um_card_originais_preservados_sem_rede(self):
        urls = [DESTINO + "&tag=canal-a-20", DESTINO + "&tag=canal-b-20"]
        identidades = []
        for canal, url in zip((-100111, -100222), urls):
            evento = await self.processar(self.mensagem(canal, url))
            identidades.append(self.assert_copia_sem_forte(evento))
            self.assertEqual(json.loads(evento["decisao"])["link"], url)
        self.assertEqual(identidades[0]["copia"], identidades[1]["copia"])
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual({o["link"] for o in self.repo.observacoes.values()}, set(urls))
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(await linhas(self.estado, "SELECT * FROM enriquecimentos"), [])

    async def test_curtos_publicam_antes_da_barreira_depois_fundem_e_ids_resolvem(self):
        urls = ["https://amzn.to/DealA", "https://amzn.to/DealB"]
        self.resolvedor.destinos = {url: DESTINO for url in urls}
        self.resolvedor.liberar.clear()
        self.pipeline.iniciar()
        mensagens = [self.mensagem(canal, url) for canal, url in zip((-100111, -100222), urls)]
        for mensagem in mensagens:
            await self.pipeline.receber(mensagem)
        await asyncio.wait_for(self.resolvedor.iniciou.wait(), 10)
        for mensagem in mensagens:
            await aguardar(lambda m=mensagem: self.finalizada(m), pipeline=self.pipeline)
        antigos = [e["id"] for e in self.repo.ativos]
        self.assertEqual(len(antigos), 2)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertFalse(self.resolvedor.liberar.is_set())
        for mensagem in mensagens:
            evento = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
            self.assertIsNotNone(evento["disponibilizado_em"])
            self.assertIsNone(json.loads(evento["identidade"])["chave"])
        self.resolvedor.liberar.set()
        await aguardar(self.enriquecimentos_finalizados, pipeline=self.pipeline)
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(len(self.repo.observacoes), 2)
        self.assertCountEqual(self.resolvedor.chamadas, urls)
        sobrevivente = self.repo.ativos[0]["id"]
        for antigo in antigos:
            self.assertEqual((await self.repo.buscar_produto(antigo))["id"], sobrevivente)
        self.assertEqual({o["link"] for o in self.repo.observacoes.values()}, set(urls))
        self.assertIsNone(self.repo.ativos[0]["identidade"]["chave"])
        self.assertIn("copia", self.repo.ativos[0]["identidade"])

    async def test_entidade_oculta_e_botao_deduplicam_somente_link_selecionado(self):
        for modo in ("entidade", "botao"):
            with self.subTest(modo=modo):
                # O modo participa do texto para manter os dois controles independentes.
                post = POST + "\nOferta " + modo
                for canal, tag in ((-100111, "canal-a-20"), (-100222, "canal-b-20")):
                    mensagem = self.mensagem(canal, DESTINO + "&tag=" + tag, post=post, modo=modo)
                    self.assertEqual(mensagem.contexto["links"][0]["rotulo"], "Comprar agora")
                    evento = await self.processar(mensagem)
                    self.assert_copia_sem_forte(evento)
                self.assertEqual(len(self.repo.ativos), 1 if modo == "entidade" else 2)
        self.assertEqual(len(self.repo.aparicoes), 4)
        self.assertEqual(self.resolvedor.chamadas, [])

    async def test_rotulo_oculto_ou_botao_diferente_nao_desaparece(self):
        for modo in ("entidade", "botao"):
            with self.subTest(modo=modo):
                await self.assert_par_separado(
                    self.mensagem(-100111, modo=modo, rotulo="Comprar no Pix"),
                    self.mensagem(-100222, modo=modo, rotulo="Comprar somente no app"))

    async def test_condicoes_do_post_inteiro_sao_preservadas(self):
        condicoes = (
            ("Vendedor: SELLER1", "Vendedor: SELLER2"),
            ("Variante: preto-128", "Variante: azul-256"),
            ("SKU: SKU-A", "SKU: SKU-B"),
            ("Quantidade: 1", "Quantidade: 2"),
            ("Kit: unitario", "Kit: duas unidades"),
            ("Estado: novo", "Estado: recondicionado"),
            ("Cupom: POUPA10", "Cupom: POUPA20"),
            ("Elegibilidade: todos os clientes", "Elegibilidade: primeira compra"),
            ("Pagamento: Pix", "Pagamento: cartão"),
            ("Frete: grátis", "Frete: R$ 20 para Sul"),
            ("Assinatura: compra avulsa", "Assinatura: recorrente"),
        )
        for primeira, segunda in condicoes:
            with self.subTest(condicao=primeira):
                await self.assert_par_separado(
                    self.mensagem(-100111, post=POST + "\n" + primeira),
                    self.mensagem(-100222, post=POST + "\n" + segunda))

    async def test_smid_e_produto_diferentes_nao_fundem_por_titulo_preco(self):
        for outra in (AMAZON + "?smid=SELLER2", "https://www.amazon.com.br/dp/B098765432?smid=SELLER1"):
            with self.subTest(url=outra):
                await self.assert_par_separado(self.mensagem(-100111), self.mensagem(-100222, outra))

    async def test_preco_diferente_nao_funde_copia(self):
        await self.assert_par_separado(self.mensagem(-100111),
            self.mensagem(-100222, post=POST.replace("2.499,90", "2.399,90")))

    async def test_curtos_mesmo_destino_com_condicao_ou_preco_diferente_nao_fundem(self):
        for indice, outro_post in enumerate((POST + "\nSomente para novos clientes",
                                             POST.replace("2.499,90", "2.399,90"))):
            with self.subTest(post=outro_post):
                urls = (f"https://amzn.to/Controle{indice}A", f"https://amzn.to/Controle{indice}B")
                self.resolvedor.destinos.update({url: DESTINO for url in urls})
                a, b = await self.assert_par_separado(
                    self.mensagem(-100111, urls[0]), self.mensagem(-100222, urls[1], post=outro_post))
                for _ in urls:
                    job = await self.estado.obter_enriquecimento(time.time())
                    self.assertIsNotNone(job)
                    await self.pipeline._enriquecer(job)
                self.assertNotEqual(self.repo.canonico(a["produto_id"]), self.repo.canonico(b["produto_id"]))

    async def test_url_ambigua_query_desconhecida_e_tokens_nao_sao_equivalencia(self):
        urls = (DESTINO + "&sku=Azul", DESTINO + "&smid=SELLER2", DESTINO + "&TAG=canal-a-20",
                MERCADO_LIVRE + "?variation=123", "https://loja.invalid/item/A")
        for url in urls:
            with self.subTest(url=url):
                a, b = await self.assert_par_separado(self.mensagem(-100111, url), self.mensagem(-100222, url))
                self.assertIsNone((json.loads(a["identidade"]).get("copia") or {}).get("chave"))
                self.assertIsNone((json.loads(b["identidade"]).get("copia") or {}).get("chave"))
        # Tokens sem regra comprovada não podem ser descartados/normalizados.
        await self.assert_par_separado(self.mensagem(-100111, DESTINO + "&linkCode=AbC"),
                                      self.mensagem(-100222, DESTINO + "&linkCode=abc"))

    async def test_outro_link_no_texto_entidade_ou_botao_nao_desaparece(self):
        for modo in ("texto", "entidade", "botao"):
            with self.subTest(modo=modo):
                await self.assert_par_separado(
                    self.mensagem(-100111, modo=modo, extra_texto="\nRegras https://regras.invalid/A"),
                    self.mensagem(-100222, modo=modo, extra_texto="\nRegras https://regras.invalid/B"))
        await self.assert_par_separado(
            self.mensagem(-100111, modo="botao", outros_botoes=[KeyboardButtonUrl("Regras", "https://regras.invalid/A")]),
            self.mensagem(-100222, modo="botao", outros_botoes=[KeyboardButtonUrl("Regras", "https://regras.invalid/B")]))
        await self.assert_par_separado(
            self.mensagem(-100111, modo="entidade", outros_ocultos=[("Regras", "https://regras.invalid/A")]),
            self.mensagem(-100222, modo="entidade", outros_ocultos=[("Regras", "https://regras.invalid/B")]))

    async def test_cache_valido_restart_deduplica_copia_sem_resolvedor(self):
        url = "https://amzn.to/CacheCopia"
        self.resolvedor.destinos = {url: DESTINO}
        await self.processar(self.mensagem(-100111, url))
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertEqual(self.resolvedor.chamadas, [url])
        await self.reiniciar()
        evento = await self.processar(self.mensagem(-100222, url))
        self.assert_copia_sem_forte(evento)
        self.assertEqual(evento["estado"], "duplicata")
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(self.resolvedor.chamadas, [])

    async def test_resposta_gravacao_perdida_retoma_copia_congelada_sem_redecidir(self):
        mensagem = self.mensagem(-100111)
        self.repo.perder_resposta_salvar = True
        await self.estado.registrar(mensagem)
        with self.assertRaises(TimeoutError):
            await self.pipeline._oferta(await self.estado.obter_oferta(time.time(), True))
        antes = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
        self.assert_copia_sem_forte(antes)
        await self.reiniciar()
        with patch("src.pipeline_identidade.avaliar_mensagem", side_effect=AssertionError("refiltrou")), \
             patch("src.pipeline_identidade.identificar", side_effect=AssertionError("reidentificou")):
            await self.pipeline._oferta(await self.estado.obter_oferta(time.time(), True))
        depois = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
        for campo in ("decisao", "hash", "identidade", "diagnostico"):
            self.assertEqual(depois[campo], antes[campo])
        await self.processar(self.mensagem(-100222))
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)

    async def test_resposta_fusao_perdida_retoma_checkpoint_sem_nova_rede(self):
        urls = ("https://amzn.to/CheckpointA", "https://amzn.to/CheckpointB")
        self.resolvedor.destinos = {url: DESTINO for url in urls}
        mensagens = [self.mensagem(canal, url) for canal, url in zip((-100111, -100222), urls)]
        congeladas = [await self.processar(mensagem) for mensagem in mensagens]
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.repo.perder_resposta_enriquecer = True
        job = await self.estado.obter_enriquecimento(time.time())
        with self.assertRaises(TimeoutError):
            await self.pipeline._enriquecer(job)
        self.assertEqual(len(self.repo.ativos), 1)
        checkpoint = (await linhas(self.estado, "SELECT * FROM enriquecimentos WHERE canal_id=?", (job["canal_id"],)))[0]
        self.assertEqual(json.loads(checkpoint["resultado"])["url_final"], DESTINO)
        self.assertCountEqual(self.resolvedor.chamadas, urls)
        await self.reiniciar()
        await self.pipeline._enriquecer(await self.estado.obter_enriquecimento(time.time()))
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(len(self.repo.ativos), 1)
        self.assertEqual(len(self.repo.aparicoes), 2)
        self.assertEqual(len(self.repo.observacoes), 2)
        self.assertTrue(await self.enriquecimentos_finalizados())
        for mensagem, antes in zip(mensagens, congeladas):
            depois = await self.estado.evento(mensagem.canal_id, mensagem.msg_id)
            for campo in ("decisao", "hash", "identidade", "diagnostico"):
                self.assertEqual(depois[campo], antes[campo])


class TestContratoFakeCopias(unittest.IsolatedAsyncioTestCase):
    """Guardas do modelo fake, não evidência de que a RPC SQL faça o mesmo."""

    def test_forte_exige_comparacao_e_copia_nao_faz_ponte(self):
        copia = {"versao": 1, "chave": "c" * 64, "comparacao": {"preco": "2499.90", "post": "sintetico"}}
        a = {"versao": 2, "chave": "a" * 64, "componentes": {"comparacao": {"vendedor": "A"}}, "copia": copia}
        b = {**copy.deepcopy(a), "chave": "b" * 64, "componentes": {"comparacao": {"vendedor": "B"}}}
        desconhecida = {**copy.deepcopy(a), "chave": None}
        equivalente = RepositorioIdentidadeFake._equivalente
        self.assertFalse(equivalente(a, b))
        self.assertFalse(equivalente(a, desconhecida))
        self.assertFalse(equivalente(desconhecida, b))
        self.assertTrue(equivalente(desconhecida, copy.deepcopy(desconhecida)))
        for mudanca in ("preco", "versao", "comparacao_forte"):
            outro = copy.deepcopy(desconhecida if mudanca != "comparacao_forte" else a)
            if mudanca == "preco":
                outro["copia"]["comparacao"]["preco"] = "2399.90"
            elif mudanca == "versao":
                outro["copia"]["versao"] = 2
            else:
                outro["componentes"]["comparacao"]["vendedor"] = "B"
            self.assertFalse(equivalente(desconhecida if mudanca != "comparacao_forte" else a, outro))

    async def test_enriquecer_copia_nao_apaga_assinatura_forte_completa(self):
        repo = RepositorioIdentidadeFake()
        job = {"canal_id": -100111, "msg_id": 1}
        forte = {"versao": 2, "chave": "a" * 64,
                 "componentes": {"comparacao": {"vendedor": "A"}, "evidencias": ["sintetica"]},
                 "campo_futuro": {"preservado": True}}
        await repo.salvar_identificada(job, {"preco": 2499.90}, forte, 48)
        apenas_copia = {"versao": 2, "chave": None, "componentes": {"comparacao": {}},
                        "copia": {"versao": 1, "chave": "c" * 64, "comparacao": {"preco": 249990}}}
        resultado = await repo.enriquecer(job, apenas_copia)
        self.assertEqual(resultado.produto_id, 1)
        self.assertEqual(repo.cards[1]["identidade"], forte)

    async def test_enriquecer_sem_chaves_preserva_card_sem_fundir(self):
        repo = RepositorioIdentidadeFake()
        incerta = {"versao": 2, "chave": None, "componentes": {"comparacao": {}}}
        for canal in (-100111, -100222):
            job = {"canal_id": canal, "msg_id": 1}
            await repo.salvar_identificada(job, {"preco": 2499.90}, incerta, 48)
            await repo.enriquecer(job, incerta)
        self.assertEqual(len(repo.ativos), 2)
        self.assertEqual(repo.aliases, {})


if __name__ == "__main__":
    unittest.main()
