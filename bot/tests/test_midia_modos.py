"""CA-002/014: modos coexistentes, SQLite reaberto e mídia local real.

Somente dados/imagens sintéticos; nenhum SDK, rede, .env ou credencial. Pillow,
conversão e disco são reais. RPC/Storage falsos NÃO provam SQL, isolamento remoto,
serviço HTTP, crash de processo nem durabilidade/permissões POSIX no Windows.
"""

import asyncio
import io
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from cenarios_identidade import (
    RepositorioIdentidadeFake, ResolvedorFake, StorageFake, TelegramFake,
    linhas, mensagem_sintetica,
)
from src.cache import CacheFiltros
from src.config import Config
from src.estado import EstadoLocal
from src.midia import ArmazenamentoLocal, ArmazenamentosMidia
from src.pipeline_identidade import PipelineIdentidade


def imagem(formato="PNG"):
    with Image.new("RGB", (96, 48), (20, 80, 160)) as origem:
        saida = io.BytesIO()
        origem.save(saida, format=formato)
        return saida.getvalue()


class TelegramImagem(TelegramFake):
    async def baixar_foto(self, canal_id, msg_id, limite):
        await super().baixar_foto(canal_id, msg_id, limite)
        dados = imagem()
        assert len(dados) <= limite
        return dados


class RepositorioRastreado(RepositorioIdentidadeFake):
    def __init__(self, trilha):
        super().__init__()
        self.trilha = trilha

    async def reservar_remocao(self, url):
        permitido = await super().reservar_remocao(url)
        self.trilha.append(("reserva", url, permitido))
        return permitido

    async def confirmar_remocao(self, url):
        # Ack sem remoção física anterior não é confirmação válida nesta fixture.
        assert self.trilha[-1] == ("delete", url)
        await super().confirmar_remocao(url)
        self.trilha.append(("ack", url))


class StorageGuardado(StorageFake):
    """Aceita só chaves Supabase explicitamente conhecidas, nunca locais/massa."""

    def __init__(self, repo, trilha):
        super().__init__()
        self.repo = repo
        self.trilha = trilha
        self.permitidas = set()
        self.enviadas = []
        self.consultadas = []

    def validar(self, chave):
        assert chave in self.permitidas and chave.endswith(".jpg"), chave

    async def url_publica(self, chave):
        self.validar(chave)
        self.consultadas.append(chave)
        return await super().url_publica(chave)

    async def enviar(self, chave, dados):
        self.validar(chave)
        self.enviadas.append(chave)
        return await super().enviar(chave, dados)

    async def remover(self, chave):
        self.validar(chave)
        url = await self.url_publica(chave)
        assert url in self.repo.reservas
        assert not any(c["foto_url"] == url for c in self.repo.ativos)
        await super().remover(chave)
        self.trilha.append(("delete", url))


class LocalRastreado(ArmazenamentoLocal):
    """Observa chamadas; transformação/publicação/inspeção/remoção são reais."""

    def __init__(self, diretorio, repo, trilha, envios):
        super().__init__(diretorio, max_entrada=10485760, max_pixels=24000000,
                         lado_max=960, max_saida=358400)
        self.repo = repo
        self.trilha = trilha
        self.envios = envios

    async def enviar(self, chave, dados):
        self.envios.append(chave)
        return await super().enviar(chave, dados)

    async def remover(self, chave):
        url = await self.url_publica(chave)
        assert url in self.repo.reservas
        assert not any(c["foto_url"] == url for c in self.repo.ativos)
        await super().remover(chave)
        assert not (self.diretorio / chave).exists()
        self.trilha.append(("delete", url))


class TestMidiaModos(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="midia-modos-")
        self.addCleanup(self.tmp.cleanup)
        raiz = Path(self.tmp.name)
        self.config = replace(Config(), state_dir=raiz / "estado",
                              midia_local_dir=raiz / "midia", shutdown_timeout=.05)
        self.trilha = []
        self.envios_locais = []
        self.repo = RepositorioRastreado(self.trilha)
        self.storage = StorageGuardado(self.repo, self.trilha)
        self.telegram = TelegramImagem()
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.pipeline = None
        self.local = None
        self.estado = EstadoLocal(self.config.state_dir)
        self.addAsyncCleanup(self.fechar)
        await self.estado.abrir()
        await self.compor()
        self.eventos = {}

    async def compor(self):
        self.local = LocalRastreado(self.config.midia_local_dir, self.repo,
                                    self.trilha, self.envios_locais)
        await self.local.preparar()
        self.destinos = ArmazenamentosMidia(self.storage, self.local)
        self.resolvedor = ResolvedorFake()
        self.pipeline = PipelineIdentidade(self.estado, self.repo, self.destinos,
            self.telegram, self.cache, self.config, resolvedor=self.resolvedor)

    async def fechar(self):
        try:
            if self.pipeline is not None:
                await self.pipeline.encerrar()
        finally:
            self.pipeline = None
            try:
                if self.local is not None:
                    await self.local.fechar()
            finally:
                self.local = None
                await self.estado.fechar()

    async def reiniciar(self, modo):
        await self.fechar()
        anterior = self.estado
        self.config = replace(self.config, midia_modo=modo)
        self.estado = EstadoLocal(self.config.state_dir)
        await self.estado.abrir()
        self.assertIsNot(self.estado, anterior)
        await self.compor()

    async def agendar(self, numero):
        # Provas fortes distintas: os três jobs não são deduplicados entre si.
        contexto = mensagem_sintetica().contexto
        contexto["identidade"]["sku"] = f"SKU-SINTETICO-{numero}"
        mensagem = mensagem_sintetica(numero, foto=True, contexto=contexto)
        await self.estado.registrar(mensagem)
        oferta = await self.estado.obter_oferta(time.time(), True)
        self.assertIsNotNone(oferta)
        downloads = self.telegram.chamadas
        await self.pipeline._oferta(oferta)
        evento = await self.estado.evento(mensagem.canal_id, numero)
        self.assertIsNotNone(evento["disponibilizado_em"])
        self.assertIsNone(self.repo.cards[evento["produto_id"]]["foto_url"])
        self.assertEqual(self.telegram.chamadas, downloads)
        self.eventos[numero] = evento
        job = await self.estado.midia(evento["produto_id"])
        self.assertEqual(job["destino"], self.config.midia_modo)
        if job["destino"] == "supabase":
            self.storage.permitidas.add(job["chave"])
            self.assertEqual(job["chave"], f"{job['produto_id']}_{mensagem.canal_id}_{numero}.jpg")
        else:
            self.assertRegex(job["chave"], r"^[a-f0-9]{32}\.webp$")
        return job

    async def claim(self, original):
        job = await self.estado.obter_midia(time.time())
        self.assertIsNotNone(job)
        self.assertEqual(job["produto_id"], original["produto_id"])
        return job

    async def interromper(self, job, objeto, metodo, *, depois):
        atingiu = asyncio.Event()
        original = getattr(objeto, metodo)

        async def barreira(*args, **kwargs):
            if depois:
                await original(*args, **kwargs)
            atingiu.set()
            await asyncio.Event().wait()

        with patch.object(objeto, metodo, side_effect=barreira):
            tarefa = asyncio.create_task(self.pipeline._midia(job))
            try:
                await asyncio.wait_for(atingiu.wait(), 10)
                self.assertFalse(tarefa.done())
            finally:
                tarefa.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tarefa

    def conferir_webp(self, chave):
        caminho = self.config.midia_local_dir / chave
        with Image.open(caminho) as final:
            self.assertEqual((final.format, final.size), ("WEBP", (96, 48)))
            final.load()
        return caminho.read_bytes(), caminho.stat().st_mtime_ns

    async def conferir_congelados(self):
        for numero, antes in self.eventos.items():
            depois = await self.estado.evento(antes["canal_id"], numero)
            for campo in ("produto_id", "decisao", "hash", "identidade", "diagnostico"):
                self.assertEqual(depois[campo], antes[campo], campo)

    async def test_supabase_local_supabase_tres_jobs_antes_de_baixar_e_restart_misto(self):
        # Objetos alheios conhecidos apenas pelo teste detectam migração/GC em massa.
        self.storage.objetos["alheia.jpg"] = b"objeto-sintetico-intocado"
        sentinela = self.config.midia_local_dir / ("f" * 32 + ".webp")
        sentinela.write_bytes(imagem("WEBP"))
        sentinela_antes = (sentinela.read_bytes(), sentinela.stat().st_mtime_ns)
        primeiro = await self.agendar(1)
        await self.reiniciar("local")
        self.assertEqual(await self.estado.midia(primeiro["produto_id"]), primeiro)
        segundo = await self.agendar(2)
        await self.reiniciar("supabase")
        terceiro = await self.agendar(3)
        originais = [primeiro, segundo, terceiro]
        for job in originais:
            self.assertEqual(await self.estado.midia(job["produto_id"]), job)
        self.assertEqual(self.telegram.chamadas, 0)
        self.assertEqual(self.storage.enviadas, [])
        self.assertEqual(self.storage.consultadas, [])
        self.assertEqual(self.envios_locais, [])
        self.assertEqual(len(self.repo.cards), 3)

        # Supabase enviado sem vínculo; local publicado sem resposta/checkpoint;
        # terceiro ainda pendente. Todas as fronteiras vêm do pipeline real.
        await self.interromper(await self.claim(primeiro), self.repo, "vincular_foto", depois=False)
        await self.interromper(await self.claim(segundo), self.local, "enviar", depois=True)
        local_antes = self.conferir_webp(segundo["chave"])
        checkpoints = [await self.estado.midia(j["produto_id"]) for j in originais]
        self.assertEqual([(j["enviado"], j["compensar"]) for j in checkpoints],
                         [(1, 0), (0, 1), (0, 0)])
        self.assertEqual(self.telegram.chamadas, 2)
        self.assertIsNone(await self.estado.obter_confirmacao())
        await self.reiniciar("supabase")
        for antes in checkpoints:
            depois = await self.estado.midia(antes["produto_id"])
            self.assertEqual(depois, {**antes, "estado": "retry"}
                             if antes["estado"] == "processando" else antes)
        self.assertEqual(self.trilha, [])
        for original in originais:
            await self.pipeline._midia(await self.claim(original))
            final = await self.estado.midia(original["produto_id"])
            self.assertEqual((final["estado"], final["compensar"]), ("pronta", 0))
            for campo in ("produto_id", "canal_id", "msg_id", "chave", "destino"):
                self.assertEqual(final[campo], original[campo])
            url = (f"/media/{original['chave']}" if original["destino"] == "local"
                   else f"https://storage.invalid/{original['chave']}")
            self.assertEqual(final["url"], url)
            self.assertEqual(self.repo.cards[original["produto_id"]]["foto_url"], url)
        self.assertIsNone(await self.estado.obter_midia(time.time()))
        self.assertEqual(self.telegram.chamadas, 3)
        self.assertEqual(self.storage.enviadas, [primeiro["chave"], terceiro["chave"]])
        self.assertEqual(self.envios_locais, [segundo["chave"]])
        self.assertEqual(self.conferir_webp(segundo["chave"]), local_antes)
        self.assertEqual((sentinela.read_bytes(), sentinela.stat().st_mtime_ns), sentinela_antes)
        self.assertEqual(self.storage.objetos, {"alheia.jpg": b"objeto-sintetico-intocado",
            primeiro["chave"]: imagem(), terceiro["chave"]: imagem()})
        self.assertEqual(self.storage.removidos, [])
        self.assertEqual(self.trilha, [])
        self.assertEqual({p.name for p in self.config.midia_local_dir.iterdir()},
                         {segundo["chave"], sentinela.name})
        self.assertEqual(self.resolvedor.chamadas, [])
        self.assertEqual(len(self.repo.aparicoes), 3)
        await self.conferir_congelados()

    async def test_local_ja_vinculada_continua_publicada_e_removivel_com_modo_supabase(self):
        await self.reiniciar("local")
        original = await self.agendar(1)
        await self.pipeline._midia(await self.claim(original))
        vinculada = await self.estado.midia(original["produto_id"])
        conteudo = self.conferir_webp(original["chave"])
        await self.reiniciar("supabase")
        self.assertEqual(await self.estado.midia(original["produto_id"]), vinculada)
        self.assertTrue(await self.local.publicada(original["chave"]))
        self.assertEqual(await self.local.url_publica(original["chave"]), vinculada["url"])
        await self.pipeline.armazenamento.remover_job(vinculada)
        self.assertEqual(self.trilha, [("reserva", vinculada["url"], False)])
        self.assertEqual(self.conferir_webp(original["chave"]), conteudo)
        self.repo.cards[original["produto_id"]]["removido"] = True
        await self.pipeline.armazenamento.remover_job(vinculada)
        self.assertFalse(await self.local.publicada(original["chave"]))
        self.assertEqual(self.trilha[1:], [("reserva", vinculada["url"], True),
            ("delete", vinculada["url"]), ("ack", vinculada["url"])])
        self.assertEqual(self.storage.consultadas, [])
        self.assertEqual(self.storage.enviadas, [])
        self.assertEqual(self.storage.removidos, [])
        self.assertEqual(self.telegram.chamadas, 1)
        await self.conferir_congelados()

    async def compensar_apagado(self, destino):
        await self.reiniciar(destino)
        original = await self.agendar(1)
        await self.interromper(await self.claim(original), self.repo, "vincular_foto", depois=False)
        enviado = await self.estado.midia(original["produto_id"])
        self.repo.cards[original["produto_id"]]["removido"] = True
        await self.reiniciar("supabase" if destino == "local" else "local")
        await self.pipeline._midia(await self.claim(original))
        final = await self.estado.midia(original["produto_id"])
        self.assertEqual((final["estado"], final["compensar"]), ("removida", 0))
        self.assertEqual((final["chave"], final["url"], final["destino"]),
                         (original["chave"], enviado["url"], destino))
        self.assertEqual(self.trilha, [("reserva", enviado["url"], True),
            ("delete", enviado["url"]), ("ack", enviado["url"])])
        self.assertEqual(self.telegram.chamadas, 1)
        self.assertEqual(self.repo.chamadas["vincular_foto"], 0)
        self.assertEqual(self.storage.removidos, [original["chave"]] if destino == "supabase" else [])
        if destino == "local":
            self.assertFalse(await self.local.publicada(original["chave"]))
            self.assertEqual(self.storage.consultadas, [])
        await self.conferir_congelados()

    async def test_compensa_por_id_apagado_local_apos_rollback(self):
        await self.compensar_apagado("local")

    async def test_compensa_por_id_apagado_supabase_com_modo_local(self):
        await self.compensar_apagado("supabase")

    async def alias_com_fotos(self, destino_perdedor):
        destino_sobrevivente = "supabase" if destino_perdedor == "local" else "local"
        await self.reiniciar(destino_sobrevivente)
        sobrevivente = await self.agendar(1)
        await self.pipeline._midia(await self.claim(sobrevivente))
        foto_sobrevivente = self.repo.cards[1]["foto_url"]
        await self.reiniciar(destino_perdedor)
        perdedor = await self.agendar(2)
        await self.interromper(await self.claim(perdedor), self.repo, "vincular_foto", depois=False)
        enviado = await self.estado.midia(2)
        # Fusão explícita do contrato fake; não é evidência de SQL/favoritos reais.
        await self.repo.enriquecer(self.eventos[2], self.repo.cards[1]["identidade"])
        self.assertEqual(self.repo.aliases, {2: 1})
        await self.reiniciar(destino_sobrevivente)
        await self.pipeline._midia(await self.claim(perdedor))
        final = await self.estado.midia(2)
        self.assertEqual((final["estado"], final["compensar"]), ("pronta", 0))
        for campo in ("produto_id", "chave", "destino", "url"):
            self.assertEqual(final[campo], enviado[campo])
        self.assertEqual(self.repo.cards[1]["foto_url"], foto_sobrevivente)
        self.assertEqual(self.trilha, [("reserva", enviado["url"], True),
            ("delete", enviado["url"]), ("ack", enviado["url"])])
        if destino_sobrevivente == "local":
            self.conferir_webp(sobrevivente["chave"])
            self.assertEqual(self.storage.removidos, [perdedor["chave"]])
        else:
            self.assertEqual(self.storage.objetos, {sobrevivente["chave"]: imagem()})
            self.assertFalse(await self.local.publicada(perdedor["chave"]))
            self.assertEqual(self.storage.removidos, [])
        self.assertEqual(self.telegram.chamadas, 2)
        await self.conferir_congelados()

    async def test_compensa_local_pelo_id_virado_alias_sem_apagar_supabase_sobrevivente(self):
        await self.alias_com_fotos("local")

    async def test_compensa_supabase_pelo_id_virado_alias_sem_apagar_local_sobrevivente(self):
        await self.alias_com_fotos("supabase")

    async def test_remover_job_pelo_alias_nao_apaga_local_adotada(self):
        await self.reiniciar("local")
        sobrevivente = await self.agendar(1)
        perdedor = await self.agendar(2)
        # Claim do sobrevivente fica pendente de execução; só o perdedor publica.
        await self.claim(sobrevivente)
        await self.pipeline._midia(await self.claim(perdedor))
        vinculada = await self.estado.midia(2)
        conteudo = self.conferir_webp(perdedor["chave"])
        await self.repo.enriquecer(self.eventos[2], self.repo.cards[1]["identidade"])
        self.assertEqual(self.repo.aliases, {2: 1})
        self.assertEqual((await self.repo.buscar_produto(2))["foto_url"], vinculada["url"])
        await self.reiniciar("supabase")
        await self.pipeline.armazenamento.remover_job(vinculada)
        # O job pendente do canônico reconhece a foto adotada sem novo download.
        await self.pipeline._midia(await self.claim(sobrevivente))
        self.assertEqual(self.trilha, [("reserva", vinculada["url"], False)])
        self.assertEqual(self.conferir_webp(perdedor["chave"]), conteudo)
        self.assertEqual(self.repo.cards[1]["foto_url"], vinculada["url"])
        self.assertEqual(self.repo.reservas, set())
        self.assertEqual(self.repo.remocoes, set())
        self.assertEqual(self.storage.consultadas, [])
        self.assertEqual(self.telegram.chamadas, 1)
        self.assertEqual(self.envios_locais, [perdedor["chave"]])
        await self.conferir_congelados()


class TestMigracaoMidiaV6(unittest.IsolatedAsyncioTestCase):
    async def test_v6_sem_destino_preserva_tres_checkpoints_e_retoma_storage_em_modo_local(self):
        with tempfile.TemporaryDirectory(prefix="midia-v6-") as temporario:
            raiz = Path(temporario)
            diretorio = raiz / "estado"
            diretorio.mkdir()
            # Schema v6 independente: nunca cria v7 para só baixar user_version.
            with closing(sqlite3.connect(diretorio / "inbox.sqlite3")) as db:
                db.row_factory = sqlite3.Row
                db.executescript("""
                    CREATE TABLE canais(canal_id INTEGER PRIMARY KEY,username TEXT NOT NULL,
                        access_hash TEXT,aliases TEXT NOT NULL DEFAULT '[]',cursor INTEGER NOT NULL DEFAULT 0,
                        bootstrap REAL NOT NULL,limite INTEGER,proxima REAL NOT NULL DEFAULT 0,
                        tentativas INTEGER NOT NULL DEFAULT 0,erro TEXT,ativo INTEGER NOT NULL DEFAULT 1,
                        geracao INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE eventos(canal_id INTEGER NOT NULL,msg_id INTEGER NOT NULL,
                        username TEXT NOT NULL,remoto_canal TEXT NOT NULL,texto TEXT NOT NULL,
                        data_origem TEXT NOT NULL,recebido_em REAL NOT NULL,origem TEXT NOT NULL,
                        tem_foto INTEGER NOT NULL,estado TEXT NOT NULL DEFAULT 'pendente',
                        tentativas INTEGER NOT NULL DEFAULT 0,proxima REAL NOT NULL DEFAULT 0,erro TEXT,
                        decisao TEXT,hash TEXT,produto_id INTEGER,resultado TEXT,finalizado_em REAL,
                        disponibilizado_em REAL,contexto TEXT NOT NULL DEFAULT '{}',
                        diagnostico TEXT NOT NULL DEFAULT '{}',identidade TEXT,
                        remoto_confirmado INTEGER NOT NULL DEFAULT 0,
                        referencia_remota INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(canal_id,msg_id));
                    CREATE TABLE midias(produto_id INTEGER PRIMARY KEY,canal_id INTEGER NOT NULL,
                        msg_id INTEGER NOT NULL,chave TEXT NOT NULL UNIQUE,estado TEXT NOT NULL DEFAULT 'pendente',
                        tentativas INTEGER NOT NULL DEFAULT 0,proxima REAL NOT NULL DEFAULT 0,erro TEXT,
                        url TEXT,enviado INTEGER NOT NULL DEFAULT 0,compensar INTEGER NOT NULL DEFAULT 0,
                        finalizado_em REAL,falha_apos_limpeza TEXT);
                    CREATE TABLE donos_hash(hash TEXT PRIMARY KEY,canal_id INTEGER NOT NULL,msg_id INTEGER NOT NULL);
                    CREATE TABLE resolucoes(username TEXT PRIMARY KEY,proxima REAL NOT NULL DEFAULT 0,
                        tentativas INTEGER NOT NULL DEFAULT 0,erro TEXT);
                    CREATE TABLE cache_urls(url TEXT PRIMARY KEY,resultado TEXT NOT NULL,
                        expira_em REAL NOT NULL,versao INTEGER NOT NULL);
                    CREATE TABLE enriquecimentos(canal_id INTEGER NOT NULL,msg_id INTEGER NOT NULL,
                        produto_id INTEGER NOT NULL,url TEXT NOT NULL,estado TEXT NOT NULL DEFAULT 'pendente',
                        tentativas INTEGER NOT NULL DEFAULT 0,proxima REAL NOT NULL DEFAULT 0,
                        resultado TEXT,erro TEXT,finalizado_em REAL,tentativas_rpc INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(canal_id,msg_id));
                    PRAGMA user_version=6;
                """)
                db.execute("INSERT INTO canais(canal_id,username,aliases,cursor,bootstrap,limite,geracao) VALUES(?,?,?,?,?,?,?)",
                           (-100111, "sintetico", '["antigo","@novo"]', 71, 123, 95, 4))
                for numero, situacao in enumerate(("pendente", "retry", "processando"), 1):
                    produto_id = 80 + numero
                    db.execute("""INSERT INTO eventos(canal_id,msg_id,username,remoto_canal,texto,data_origem,
                        recebido_em,origem,tem_foto,estado,tentativas,decisao,hash,produto_id,contexto,
                        diagnostico,identidade,referencia_remota,disponibilizado_em,finalizado_em)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (-100111, numero, "antigo", "@antigo", "Oferta congelada sintética",
                         "2026-01-01T00:00:00+00:00", 123, "historico", 1, "aprovada", 7,
                         json.dumps({"titulo": "Decisão preservada", "preco": 0}),
                         f"HASH-CONGELADO-{numero}", produto_id, '{"links": []}',
                         '{"snapshot": 9}', '{"versao": 2, "congelada": true}', 1, 124, 125))
                    chave = f"{produto_id}_-100111_{numero}.jpg"
                    db.execute("""INSERT INTO midias VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (produto_id, -100111, numero, chave, situacao, numero + 2, 17 + numero,
                         f"erro_checkpoint_{numero}", f"https://storage.invalid/{chave}" if numero > 1 else None,
                         int(numero > 1), int(numero == 3), None,
                         "falha_congelada" if numero == 3 else None))
                antes = [dict(r) for r in db.execute("SELECT * FROM midias ORDER BY produto_id")]
                eventos = [dict(r) for r in db.execute("SELECT * FROM eventos ORDER BY msg_id")]
                canal = dict(db.execute("SELECT * FROM canais").fetchone())
                self.assertNotIn("destino", {r[1] for r in db.execute("PRAGMA table_info(midias)")})
                db.commit()

            trilha = []
            repo = RepositorioRastreado(trilha)
            storage = StorageGuardado(repo, trilha)
            for job in antes:
                storage.permitidas.add(job["chave"])
                repo.cards[job["produto_id"]] = {"id": job["produto_id"], "foto_url": None,
                    "removido": job["produto_id"] == 83}
                if job["enviado"]:
                    storage.objetos[job["chave"]] = imagem()
            cache = CacheFiltros(repo)
            await cache.atualizar()
            telegram = TelegramImagem()
            config = replace(Config(), state_dir=diretorio, midia_modo="local",
                             midia_local_dir=raiz / "midia")
            local = LocalRastreado(config.midia_local_dir, repo, trilha, [])
            try:
                await local.preparar()
                # Duas aberturas reais provam reaplicabilidade antes de consumir jobs.
                for _ in range(2):
                    estado = EstadoLocal(diretorio)
                    try:
                        await estado.abrir()
                        self.assertEqual((await linhas(estado, "PRAGMA user_version"))[0]["user_version"], 7)
                        self.assertEqual((await linhas(estado, "PRAGMA synchronous"))[0]["synchronous"], 2)
                        self.assertEqual((await linhas(estado, "PRAGMA journal_mode"))[0]["journal_mode"], "wal")
                        self.assertEqual(await linhas(estado, "SELECT * FROM eventos ORDER BY msg_id"), eventos)
                        self.assertEqual(await estado.canal(-100111), canal)
                        for original in antes:
                            self.assertEqual(await estado.midia(original["produto_id"]),
                                {**original, "destino": "supabase",
                                 "estado": "retry" if original["estado"] == "processando" else original["estado"]})
                    finally:
                        await estado.fechar()
                estado = EstadoLocal(diretorio)
                await estado.abrir()
                resolvedor = ResolvedorFake()
                pipeline = PipelineIdentidade(estado, repo, ArmazenamentosMidia(storage, local),
                                               telegram, cache, config, resolvedor=resolvedor)
                try:
                    for original in antes:
                        job = await estado.obter_midia(time.time())
                        self.assertEqual(job["produto_id"], original["produto_id"])
                        await pipeline._midia(job)
                        final = await estado.midia(job["produto_id"])
                        self.assertEqual(final["destino"], "supabase")
                        self.assertEqual(final["chave"], original["chave"])
                        self.assertEqual(final["estado"], "removida" if job["produto_id"] == 83 else "pronta")
                        if job["produto_id"] != 83:
                            self.assertEqual(final["url"], f"https://storage.invalid/{original['chave']}")
                    self.assertIsNone(await estado.obter_midia(time.time()))
                    self.assertEqual(await linhas(estado, "SELECT * FROM eventos ORDER BY msg_id"), eventos)
                    self.assertEqual(telegram.chamadas, 1)
                    self.assertEqual(storage.enviadas, [antes[0]["chave"]])
                    self.assertEqual(storage.removidos, [antes[2]["chave"]])
                    self.assertEqual(set(storage.objetos), {antes[0]["chave"], antes[1]["chave"]})
                    self.assertEqual(trilha, [("reserva", antes[2]["url"], True),
                        ("delete", antes[2]["url"]), ("ack", antes[2]["url"])])
                    self.assertEqual(local.envios, [])
                    self.assertEqual(list(config.midia_local_dir.iterdir()), [])
                    self.assertEqual(resolvedor.chamadas, [])
                finally:
                    await pipeline.encerrar()
                    await estado.fechar()
            finally:
                await local.fechar()


if __name__ == "__main__":
    unittest.main()
