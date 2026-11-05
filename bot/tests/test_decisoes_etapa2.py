"""Contratos da etapa 2 com mensagens sintéticas e SQLite temporário verdadeiro."""

import contextlib
import io
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from previa import main as previa_main
from src.avaliacao import avaliar_mensagem
from src.cache import CacheFiltros
from src.config import Config
from src.dedup import gerar_hash
from src.estado import EstadoLocal
from src.filters import preparar_filtros
from src.pipeline import Pipeline
from src.repository import CAMPOS_REMOTOS, COLUNAS_FILTROS, RepositorioSupabase
from tests.test_pipeline import StorageFake, TelegramFake, mensagem
from tests.test_repository import ClienteFake, ConsultaFake


class ConsultaEstrita(ConsultaFake):
    def upsert(self, registro: dict, **kwargs: object) -> "ConsultaEstrita":
        if self.tabela == "produtos":
            extras = set(registro) - set(CAMPOS_REMOTOS)
            if extras:
                raise AssertionError(f"Campo interno enviado ao remoto: {extras}")
        return super().upsert(registro, **kwargs)


class ClienteEstrito(ClienteFake):
    def table(self, tabela: str) -> ConsultaEstrita:
        return ConsultaEstrita(self, tabela)


class TestDecisoesEtapa2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self.tmp.name)
        self.estado = EstadoLocal(self.diretorio)
        await self.estado.abrir()
        self.cliente = ClienteEstrito()
        self.repo = RepositorioSupabase(self.cliente)
        self.cache = CacheFiltros(self.repo)
        await self.cache.atualizar()
        self.config = replace(Config(), state_dir=self.diretorio, shutdown_timeout=0.01)
        self.pipeline = Pipeline(self.estado, self.repo, StorageFake(), TelegramFake(), self.cache, self.config)

    async def asyncTearDown(self) -> None:
        await self.pipeline.encerrar()
        await self.estado.fechar()
        self.tmp.cleanup()

    async def job(self, texto: str | None = None, msg_id: int = 1) -> dict:
        await self.estado.registrar(mensagem(texto=texto, msg_id=msg_id))
        return await self.estado.obter_oferta(time.time(), True)

    async def test_diagnostico_congelado_antes_primeiro_efeito_e_payload_explicito(self) -> None:
        self.cache.filtros = [{"id": 1, "palavras_chave": ["ssd", "kingston"], "modo_palavras": "todas"}]
        texto = "OFERTA IMPERDÍVEL\nSSD Kingston NV2 1 TB\nPor R$ 299,90\nhttps://loja.example/Produto?Code=ABC"
        job = await self.job(texto)
        salvar = self.repo.salvar_oferta

        async def conferir(*args: object, **kwargs: object) -> object:
            evento = await self.estado.evento(job["canal_id"], job["msg_id"])
            self.assertIsNotNone(evento["decisao"])
            self.assertIsNotNone(evento["hash"])
            diagnostico = json.loads(evento["diagnostico"])
            self.assertEqual(diagnostico["motivo"], "aceita_por_regra")
            self.assertEqual(diagnostico["regra"], 1)
            return await salvar(*args, **kwargs)

        self.repo.salvar_oferta = conferir
        await self.pipeline._oferta(job)
        produto = self.cliente.tabelas["produtos"][0]
        self.assertTrue(set(produto) <= set(CAMPOS_REMOTOS) | {"id", "criado_em"})
        self.assertNotIn("conteudo", produto)
        self.assertNotIn("diagnostico", produto)
        self.assertEqual(produto["preco"], 299.9)
        self.assertIn("SSD Kingston", produto["titulo"])

    async def test_rejeicao_terminal_motivos_por_regra_sem_rede_sem_loop(self) -> None:
        self.cache.filtros = [{"id": 1, "palavras_chave": ["mouse"]}, {"id": 2, "preco_max": 0}]
        job = await self.job()
        self.repo.salvar_oferta = AsyncMock(side_effect=AssertionError("rede indevida"))
        await self.pipeline._oferta(job)
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        self.assertEqual(evento["estado"], "descartada")
        diagnostico = json.loads(evento["diagnostico"])
        self.assertEqual(diagnostico["motivo"], "nenhuma_regra_aceitou")
        self.assertEqual(len(diagnostico["por_regra"]), 2)
        self.assertIsNone(await self.estado.obter_oferta(time.time() + 100, True))
        self.repo.salvar_oferta.assert_not_awaited()

    async def test_ambiguo_e_divulgacao_nao_contaminam_configuracao(self) -> None:
        for i, texto in enumerate([
            "Entre no grupo de promoções https://t.me/exemplo",
            "SSD Kingston R$ 299,90\nHeadset Logitech R$ 149,90\nhttps://loja.test/kit",
        ], 1):
            job = await self.job(texto, i)
            await self.pipeline._oferta(job)
            evento = await self.estado.evento(job["canal_id"], job["msg_id"])
            self.assertEqual(evento["estado"], "descartada")
            self.assertEqual(json.loads(evento["diagnostico"])["motivo"],
                             "sem_evidencia_de_oferta" if i == 1 else "multiplas_ofertas")
        await self.pipeline._oferta(await self.job(msg_id=3))
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(self.cache.filtros, [])

    async def test_commit_ambiguo_hash_antigo_sem_nova_extracao_avaliacao_ou_hash(self) -> None:
        job = await self.job()
        produto = {"titulo": "Notebook antigo", "preco": 99.9, "link": "https://loja.test/Antigo",
                   "conteudo": "NÃO ENVIAR", "diagnostico": {"privado": "NÃO ENVIAR"}}
        hash_antigo = "b" * 32
        await self.estado.decidir(job, produto, hash_antigo, diagnostico={"motivo": "aceita_por_regra"})
        await self.estado.adiar_oferta(job, "retry", 0, "teste")
        job = await self.estado.obter_oferta(time.time(), True)
        self.cliente.falha = ("produtos", "upsert", "depois")
        with patch("src.pipeline.gerar_hash", side_effect=AssertionError("hash recalculado")), \
             patch("src.repository.gerar_hash", side_effect=AssertionError("hash remoto recalculado")), \
             patch("src.avaliacao.extrair_detalhado", side_effect=AssertionError("extração repetida")), \
             patch("src.avaliacao.avaliar_produto", side_effect=AssertionError("avaliação repetida")):
            with self.assertRaises(TimeoutError):
                await self.pipeline._oferta(job)
            await self.estado.fechar()
            self.estado = EstadoLocal(self.diretorio)
            await self.estado.abrir()
            self.cache.filtros = None
            self.pipeline.estado = self.estado
            self.pipeline.repositorio = RepositorioSupabase(self.cliente)
            self.cliente.tabelas["produtos"][0]["criado_em"] = "2000-01-01T00:00:00+00:00"
            job = await self.estado.obter_oferta(time.time(), False)
            self.assertIsNotNone(job)
            await self.pipeline._oferta(job)
        evento = await self.estado.evento(job["canal_id"], job["msg_id"])
        self.assertEqual(evento["estado"], "aprovada")
        self.assertEqual(evento["hash"], hash_antigo)
        self.assertEqual(json.loads(evento["decisao"]), produto)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)
        self.assertEqual(self.cliente.tabelas["produtos"][0]["dedup_hash"], hash_antigo)
        self.assertNotIn("diagnostico", self.cliente.tabelas["produtos"][0])
        await self.estado.registrar(mensagem())
        self.assertIsNone(await self.estado.obter_oferta(time.time(), True))

    async def test_decisao_legada_sem_hash_usa_so_produto_congelado(self) -> None:
        job = await self.job()
        produto = {"titulo": "Produto legado", "preco": None, "link": "https://loja.test/legado"}
        await self.estado.decidir(job, produto, gerar_hash(produto))

        def apagar_hash() -> None:
            with self.estado.db:
                self.estado.db.execute("UPDATE eventos SET hash=NULL")

        await self.estado._executar(apagar_hash)
        await self.estado.adiar_oferta(job, "retry", 0, "legado")
        job = await self.estado.obter_oferta(time.time(), True)
        with patch("src.avaliacao.extrair_detalhado", side_effect=AssertionError("extração repetida")), \
             patch("src.pipeline.gerar_hash", wraps=gerar_hash) as hash_:
            await self.pipeline._oferta(job)
        hash_.assert_called_once_with(produto)
        self.assertEqual(self.cliente.tabelas["produtos"][0]["dedup_hash"], gerar_hash(produto))

    async def test_repositorio_projeta_mesmo_chamador_legado_expansivo(self) -> None:
        registro = {"titulo": "SSD", "preco": 1, "canal_origem": "canal", "telegram_msg_id": 5,
                    "conteudo": "privado", "motivos": ["privado"], "contexto": {}, "foto_url": None}
        await self.repo.salvar_oferta(registro, [])
        self.assertNotIn("conteudo", self.cliente.tabelas["produtos"][0])
        self.assertNotIn("contexto", self.cliente.tabelas["produtos"][0])

    async def test_schema_exige_novas_colunas_sem_fallback(self) -> None:
        class ConsultaSemSchema:
            def select(self, campos: str) -> "ConsultaSemSchema":
                self.campos = campos
                return self

            def eq(self, *args: object) -> "ConsultaSemSchema":
                return self

            async def execute(self) -> None:
                if "tipo_regra" in self.campos:
                    raise RuntimeError("coluna_ausente")
                raise AssertionError("Não pode mascarar falta de schema com select *")

        consulta = ConsultaSemSchema()
        self.cliente.table = lambda _: consulta
        with self.assertRaises(RuntimeError):
            await self.cache.atualizar()
        self.assertEqual(consulta.campos, COLUNAS_FILTROS)
        self.assertEqual(self.cache.filtros, [])

    async def test_logs_motivos_nao_vazam_termos_cupom_ou_urls(self) -> None:
        self.cache.filtros = [{"id": 1, "palavras_chave": ["TERMO_PRIVADO"]}]
        job = await self.job("SSD Kingston R$ 299,90\nCupom: AbC123\nhttps://loja.test/Privado?Token=segredo")
        with self.assertLogs("dealbot", level="INFO") as logs:
            await self.pipeline._oferta(job)
        saida = "\n".join(logs.output)
        for segredo in ("TERMO_PRIVADO", "AbC123", "https://", "segredo", "Kingston"):
            self.assertNotIn(segredo, saida)
        self.assertIn("palavra_ausente", saida)


class TestPreviaEtapa2(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.texto = "SSD Kingston NV2\nPor R$ 299,90\nhttps://loja.test/Produto"
        self.regras = [{"id": 1, "palavras_chave": ["ssd", "kingston"], "modo_palavras": "todas"}]
        (self.dir / "mensagem.txt").write_text(self.texto, encoding="utf-8")
        (self.dir / "filtros.json").write_text(json.dumps(self.regras), encoding="utf-8")
        self.args = ["--mensagem", str(self.dir / "mensagem.txt"), "--filtros", str(self.dir / "filtros.json")]

    def rodar(self, args: list[str] | None = None) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
             patch("socket.socket", side_effect=AssertionError("rede proibida")), patch.dict("os.environ", {}, clear=True):
            codigo = previa_main(args or self.args)
        return codigo, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_previa_mesmo_resultado_producao_sem_tokens_ou_rede(self) -> None:
        codigo, saida = self.rodar()
        producao = avaliar_mensagem(self.texto, preparar_filtros(self.regras))
        self.assertEqual(codigo, 0)
        self.assertEqual(saida["produto"], producao.extracao.produto)
        self.assertEqual(saida["diagnostico"], producao.diagnostico)
        self.assertTrue(saida["aceita"])

    def test_previa_rejeicao_valida_retorna_zero(self) -> None:
        (self.dir / "mensagem.txt").write_text("Entre no grupo https://t.me/exemplo", encoding="utf-8")
        codigo, saida = self.rodar()
        self.assertEqual(codigo, 0)
        self.assertFalse(saida["aceita"])
        self.assertEqual(saida["diagnostico"]["motivo"], "sem_evidencia_de_oferta")

    def test_previa_config_entrada_contexto_invalidos_retornam_dois(self) -> None:
        for dados in ("invalid-json", '[{"tipo_regra":"bloqueio_global"}]', '{"nao":"lista"}'):
            (self.dir / "filtros.json").write_text(dados, encoding="utf-8")
            codigo, saida = self.rodar()
            self.assertEqual(codigo, 2)
            self.assertEqual(saida["erro"], "entrada_ou_configuracao_invalida")
        (self.dir / "filtros.json").write_text("[]", encoding="utf-8")
        for contexto in ([], {"codigos": [{"offset": -1, "length": 4}]}, {"links": ["url"]}):
            caminho = self.dir / "contexto.json"
            caminho.write_text(json.dumps(contexto), encoding="utf-8")
            self.assertEqual(self.rodar([*self.args, "--contexto", str(caminho)])[0], 2)

    def test_previa_contexto_botao_e_codigo_de_falha_tecnica(self) -> None:
        caminho = self.dir / "contexto.json"
        caminho.write_text(json.dumps({"links": [{"url": "https://loja.test/Outro", "origem": "botao", "rotulo": "Comprar"}]}), encoding="utf-8")
        self.assertEqual(self.rodar([*self.args, "--contexto", str(caminho)])[0], 0)
        with patch("previa.avaliar_mensagem", side_effect=RuntimeError("SEGREDO")):
            codigo, saida = self.rodar()
        self.assertEqual(codigo, 1)
        self.assertEqual(saida, {"erro": "falha_tecnica"})
