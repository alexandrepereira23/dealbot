"""Contratos offline: SDK fluente fake, sem ambiente ou serviços do usuário."""

import asyncio
import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from src.db import criar_cliente, fechar_cliente
from src.dedup import gerar_hash
from src.midia import ArmazenamentoSupabase
from src.repository import QUANTIDADE_TRAVAS, RepositorioSupabase


class ConsultaFake:
    def __init__(self, cliente: "ClienteFake", tabela: str) -> None:
        self.cliente = cliente
        self.tabela = tabela
        self.operacao = "select"
        self.campos = "*"
        self.filtros: list[tuple[str, str, Any]] = []
        self.registro: dict = {}
        self.limite: int | None = None
        self.ordenacao: tuple[str, bool] | None = None
        self.ignorar_duplicados = False

    def select(self, campos: str) -> "ConsultaFake":
        self.campos = campos
        return self

    def eq(self, campo: str, valor: Any) -> "ConsultaFake":
        self.filtros.append(("eq", campo, valor))
        return self

    def in_(self, campo: str, valores: list) -> "ConsultaFake":
        self.filtros.append(("in", campo, valores))
        return self

    def or_(self, filtro: str) -> "ConsultaFake":
        valores = [parte.removeprefix("canal_origem.ilike.").replace("\\_", "_").lower()
                   for parte in filtro.split(",")]
        self.filtros.append(("canal_ci", "canal_origem", valores))
        return self

    def gte(self, campo: str, valor: str) -> "ConsultaFake":
        self.filtros.append(("gte", campo, valor))
        return self

    def is_(self, campo: str, valor: str) -> "ConsultaFake":
        self.filtros.append(("is", campo, valor))
        return self

    def order(self, campo: str, desc: bool = False) -> "ConsultaFake":
        self.ordenacao = (campo, desc)
        return self

    def limit(self, valor: int) -> "ConsultaFake":
        self.limite = valor
        return self

    def upsert(
        self, registro: dict, *, on_conflict: str, ignore_duplicates: bool = False
    ) -> "ConsultaFake":
        assert on_conflict == "canal_origem,telegram_msg_id"
        self.operacao = "upsert"
        self.registro = copy.deepcopy(registro)
        self.ignorar_duplicados = ignore_duplicates
        return self

    def update(self, registro: dict) -> "ConsultaFake":
        self.operacao = "update"
        self.registro = copy.deepcopy(registro)
        return self

    def _corresponde(self, linha: dict) -> bool:
        for operador, campo, valor in self.filtros:
            atual = linha.get(campo)
            if operador == "eq" and atual != valor:
                return False
            if operador == "in" and atual not in valor:
                return False
            if operador == "canal_ci" and (atual is None or atual.lower() not in valor):
                return False
            if operador == "gte" and (atual is None or atual < valor):
                return False
            if operador == "is" and (valor != "null" or atual is not None):
                return False
        return True

    async def execute(self) -> Any:
        # Cede execução para expor races que um fake totalmente imediato ocultaria.
        await asyncio.sleep(self.cliente.atraso)
        self.cliente.consultas.append((self.tabela, self.operacao, copy.deepcopy(self.filtros)))
        self.cliente.disparar_falha(self.tabela, self.operacao, "antes")
        if self.cliente.resposta_incompleta:
            self.cliente.resposta_incompleta = False
            return SimpleNamespace(data=None)
        linhas = self.cliente.tabelas[self.tabela]
        if self.operacao == "upsert":
            existente = next((linha for linha in linhas if all(
                linha.get(campo) == self.registro.get(campo)
                for campo in ("canal_origem", "telegram_msg_id")
            )), None)
            if existente is not None:
                if self.ignorar_duplicados:
                    dados = []
                else:
                    existente.update(self.registro)
                    dados = [existente]
            else:
                novo = {"id": self.cliente.proximo_id, **self.registro}
                self.cliente.proximo_id += 1
                if self.tabela == "produtos":
                    novo.setdefault("foto_url", None)
                    novo.setdefault("criado_em", datetime.now(timezone.utc).isoformat())
                linhas.append(novo)
                dados = [novo]
        elif self.operacao == "update":
            if self.cliente.antes_atualizar is not None:
                self.cliente.antes_atualizar()
                self.cliente.antes_atualizar = None
            dados = [linha for linha in linhas if self._corresponde(linha)]
            for linha in dados:
                linha.update(self.registro)
        else:
            dados = [linha for linha in linhas if self._corresponde(linha)]
            if self.ordenacao:
                campo, desc = self.ordenacao
                dados.sort(key=lambda linha: linha[campo], reverse=desc)
            if self.limite is not None:
                dados = dados[:self.limite]
            if self.campos != "*":
                dados = [{campo: linha[campo] for campo in self.campos.split(",") if campo in linha}
                         for linha in dados]
        self.cliente.disparar_falha(self.tabela, self.operacao, "depois")
        return SimpleNamespace(data=copy.deepcopy(dados))


class ClienteFake:
    def __init__(self) -> None:
        self.tabelas: dict[str, list[dict]] = {
            "produtos": [], "produto_aparicoes": [], "filtros": [], "canais": [],
        }
        self.proximo_id = 1
        self.falha: tuple[str, str, str] | None = None
        self.consultas: list[tuple] = []
        self.atraso = 0.0
        self.resposta_incompleta = False
        self.antes_atualizar: Any = None

    def table(self, tabela: str) -> ConsultaFake:
        return ConsultaFake(self, tabela)

    def disparar_falha(self, tabela: str, operacao: str, momento: str) -> None:
        if self.falha == (tabela, operacao, momento):
            self.falha = None
            raise TimeoutError("segredo-fake-na-excecao")


class TestRepositorio(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cliente = ClienteFake()
        self.repo = RepositorioSupabase(self.cliente)

    @staticmethod
    def registro(canal: str = "canal", mensagem: int = 10, **dados: Any) -> dict:
        return {
            "titulo": "Notebook", "preco": 1999.90, "link": "https://loja.test/notebook",
            "canal_origem": canal, "telegram_msg_id": mensagem, "foto_url": None,
            "raw_text": "Oferta", "data_oferta": "2026-10-01T10:00:00+00:00",
            **dados,
        }

    def envelhecer(self) -> None:
        for produto in self.cliente.tabelas["produtos"]:
            produto["criado_em"] = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()

    async def test_novo_preserva_hash_dados_e_limita_raw_text(self) -> None:
        registro = self.registro(raw_text="x" * 2100, cupom="TESTE")
        resultado = await self.repo.salvar_oferta(registro, [])
        produto = self.cliente.tabelas["produtos"][0]
        self.assertEqual(resultado.status, "novo")
        self.assertIsNone(resultado.foto_url)
        self.assertEqual(produto["dedup_hash"], gerar_hash(registro))
        self.assertEqual(len(produto["raw_text"]), 2000)
        self.assertEqual(len(registro["raw_text"]), 2100)
        self.assertEqual(produto["data_oferta"], registro["data_oferta"])
        self.assertEqual(produto["cupom"], "TESTE")
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)

    async def test_commit_produto_com_resposta_perdida_retry_apos_48h(self) -> None:
        self.cliente.falha = ("produtos", "upsert", "depois")
        with self.assertRaises(TimeoutError):
            await self.repo.salvar_oferta(self.registro(), [])
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(self.cliente.tabelas["produto_aparicoes"], [])
        self.envelhecer()
        produto = self.cliente.tabelas["produtos"][0]
        produto["foto_url"] = "https://storage.test/antiga.jpg"
        criado_em = produto["criado_em"]
        # Repositório novo simula reinício, sem cache de ID em memória.
        resultado = await RepositorioSupabase(self.cliente).salvar_oferta(self.registro(), [])
        self.assertEqual(resultado.status, "retomado")
        self.assertEqual(resultado.produto_id, produto["id"])
        self.assertEqual(resultado.foto_url, produto["foto_url"])
        self.assertEqual(produto["criado_em"], criado_em)
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)

    async def test_falha_parcial_de_aparicao_propaga_e_retry_completa(self) -> None:
        self.cliente.falha = ("produto_aparicoes", "upsert", "antes")
        with self.assertRaises(TimeoutError):
            await self.repo.salvar_oferta(self.registro(), [])
        self.envelhecer()
        resultado = await self.repo.salvar_oferta(self.registro(), [])
        self.assertEqual(resultado.status, "retomado")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)

    async def test_commit_aparicao_duplicada_resposta_perdida_apos_48h(self) -> None:
        original = await self.repo.salvar_oferta(self.registro(), [])
        self.cliente.falha = ("produto_aparicoes", "upsert", "depois")
        outro = self.registro("@outro", 22)
        with self.assertRaises(TimeoutError):
            await self.repo.salvar_oferta(outro, [])
        self.envelhecer()
        resultado = await self.repo.salvar_oferta({**outro, "canal_origem": "renomeado"}, ["outro"])
        self.assertEqual(resultado.produto_id, original.produto_id)
        self.assertEqual(resultado.status, "duplicado")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        aparicoes = self.cliente.tabelas["produto_aparicoes"]
        self.assertEqual(len(aparicoes), 2)
        self.assertEqual(aparicoes[1]["canal_origem"], "@outro")

    async def test_duplicata_no_mesmo_canal_preserva_tipo_em_retry_com_vinculo(self) -> None:
        original = await self.repo.salvar_oferta(self.registro(), [])
        outro = self.registro("canal", 11)
        self.cliente.falha = ("produto_aparicoes", "upsert", "antes")
        vinculados = []

        async def ao_vincular(produto_id: int) -> None:
            vinculados.append(produto_id)

        with self.assertRaises(TimeoutError):
            await self.repo.salvar_oferta(outro, [], ao_vincular=ao_vincular)
        self.assertEqual(vinculados, [original.produto_id])
        self.envelhecer()
        resultado = await self.repo.salvar_oferta(outro, [], produto_id=vinculados[0])
        self.assertEqual(resultado.status, "duplicado")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 2)

    async def test_hash_concorrente_entre_canais_tem_um_card(self) -> None:
        resultados = await asyncio.gather(*(
            self.repo.salvar_oferta(self.registro(f"canal_{i}", i + 1), [])
            for i in range(20)
        ))
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 20)
        self.assertEqual(sum(r.status == "novo" for r in resultados), 1)
        self.assertEqual(sum(r.status == "duplicado" for r in resultados), 19)
        self.assertEqual(len({r.produto_id for r in resultados}), 1)
        self.assertEqual(len(self.repo._travas), QUANTIDADE_TRAVAS)

    async def test_mesmo_evento_concorrente_com_arroba_nao_duplica_aparicao(self) -> None:
        resultados = await asyncio.gather(
            self.repo.salvar_oferta(self.registro("@Canal"), ["Canal"]),
            self.repo.salvar_oferta(self.registro("canal"), ["@Canal"]),
        )
        self.assertEqual({r.status for r in resultados}, {"novo", "retomado"})
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(len(self.cliente.tabelas["produto_aparicoes"]), 1)

    async def test_alias_produto_antigo_reutiliza_chave_textual(self) -> None:
        await self.repo.salvar_oferta(self.registro("@Antigo"), [])
        self.cliente.tabelas["produto_aparicoes"].clear()
        self.envelhecer()
        resultado = await self.repo.salvar_oferta(self.registro("novo"), ["Antigo"])
        self.assertEqual(resultado.status, "retomado")
        self.assertEqual(self.cliente.tabelas["produto_aparicoes"][0]["canal_origem"], "@Antigo")

    async def test_alias_legado_caixa_desconhecida_e_underscore_literal(self) -> None:
        await self.repo.salvar_oferta(self.registro("Canal_Ofertas"), [])
        self.envelhecer()
        resultado = await self.repo.salvar_oferta(self.registro("canal_ofertas"), [])
        self.assertEqual(resultado.status, "retomado")
        self.assertEqual(len(self.cliente.tabelas["produtos"]), 1)
        self.assertEqual(self.cliente.tabelas["produto_aparicoes"][0]["canal_origem"], "Canal_Ofertas")

    async def test_foto_valida_e_criado_em_nao_sao_sobrescritos(self) -> None:
        anterior = await self.repo.salvar_oferta(self.registro(foto_url="https://s.test/1.jpg"), [])
        produto = self.cliente.tabelas["produtos"][0]
        antes = copy.deepcopy(produto)
        retomado = await self.repo.salvar_oferta(self.registro(titulo="Novo título"), [])
        self.assertEqual(retomado.foto_url, anterior.foto_url)
        self.assertEqual(produto, antes)
        duplicado = await self.repo.salvar_oferta(self.registro("outro", 20), [])
        self.assertEqual(duplicado.status, "duplicado")
        self.assertEqual(duplicado.foto_url, anterior.foto_url)

    async def test_janela_48h_vale_para_evento_novo_nao_para_retry(self) -> None:
        primeiro = await self.repo.salvar_oferta(self.registro(), [])
        self.envelhecer()
        segundo = await self.repo.salvar_oferta(self.registro("outro", 20), [])
        self.assertEqual(segundo.status, "novo")
        self.assertNotEqual(primeiro.produto_id, segundo.produto_id)

    async def test_conflito_ignorado_reconcilia_sem_mutar_produto(self) -> None:
        await self.repo.salvar_oferta(self.registro(foto_url="https://s.test/1.jpg"), [])
        self.envelhecer()
        antes = copy.deepcopy(self.cliente.tabelas["produtos"][0])
        reconciliar = self.repo._reconciliar
        chamadas = 0

        async def omitir_primeira(msg_id: int, aliases: list[str]) -> Any:
            nonlocal chamadas
            chamadas += 1
            if chamadas == 1:
                return None
            return await reconciliar(msg_id, aliases)

        with patch.object(self.repo, "_reconciliar", side_effect=omitir_primeira):
            resultado = await self.repo.salvar_oferta(self.registro(), [])
        self.assertEqual(resultado.status, "retomado")
        self.assertEqual(self.cliente.tabelas["produtos"][0], antes)

    async def test_atualizacao_foto_nullable_e_produto_removido(self) -> None:
        resultado = await self.repo.salvar_oferta(self.registro(), [])
        self.assertEqual(await self.repo.vincular_foto(resultado.produto_id, "https://s.test/1.jpg"), "atualizada")
        self.assertEqual(await self.repo.vincular_foto(resultado.produto_id, "https://s.test/2.jpg"), "existente")
        self.assertEqual((await self.repo.buscar_produto(resultado.produto_id))["foto_url"], "https://s.test/1.jpg")
        self.cliente.tabelas["produtos"].clear()
        self.assertEqual(await self.repo.vincular_foto(resultado.produto_id, "https://s.test/1.jpg"), "removida")
        self.assertIsNone(await self.repo.buscar_produto(resultado.produto_id))
        self.assertEqual(self.cliente.tabelas["produtos"], [])

    async def test_produto_removido_entre_busca_e_update_nao_ressuscita(self) -> None:
        resultado = await self.repo.salvar_oferta(self.registro(), [])
        self.cliente.antes_atualizar = self.cliente.tabelas["produtos"].clear
        self.assertEqual(await self.repo.vincular_foto(resultado.produto_id, "https://s.test/1.jpg"), "removida")
        self.assertEqual(self.cliente.tabelas["produtos"], [])

    async def test_foto_concorrente_preservada_por_update_condicional(self) -> None:
        resultado = await self.repo.salvar_oferta(self.registro(), [])
        produto = self.cliente.tabelas["produtos"][0]
        self.cliente.antes_atualizar = lambda: produto.update(foto_url="https://s.test/outra.jpg")
        self.assertEqual(await self.repo.vincular_foto(resultado.produto_id, "https://s.test/1.jpg"), "existente")
        self.assertEqual(produto["foto_url"], "https://s.test/outra.jpg")

    async def test_configuracao_vazia_valida_difere_de_falha(self) -> None:
        self.assertEqual(await self.repo.carregar_filtros(), [])
        self.assertEqual(await self.repo.listar_canais(), [])
        self.cliente.tabelas["canais"] = [{"username": "@Canal", "ativo": True}, {"username": "fora", "ativo": False}]
        self.assertEqual(await self.repo.listar_canais(), ["@Canal"])
        self.cliente.resposta_incompleta = True
        with self.assertRaisesRegex(RuntimeError, "Resposta incompleta"):
            await self.repo.carregar_filtros()

    async def test_timeout_real_nao_inventa_sucesso_nem_imprime_erro(self) -> None:
        self.cliente.atraso = 0.05
        repo = RepositorioSupabase(self.cliente, timeout=0.001)
        with patch("builtins.print") as imprimir:
            with self.assertRaises(TimeoutError):
                await repo.salvar_oferta(self.registro(), [])
        imprimir.assert_not_called()
        self.assertEqual(self.cliente.tabelas["produtos"], [])

    async def test_resposta_incompleta_nao_e_sucesso(self) -> None:
        self.cliente.resposta_incompleta = True
        with self.assertRaisesRegex(RuntimeError, "Resposta incompleta"):
            await self.repo.salvar_oferta(self.registro(), [])


class BucketFake:
    def __init__(self) -> None:
        self.objetos: dict[str, bytes] = {}
        self.opcoes: list[dict] = []
        self.perder_resposta = False
        self.url: Any = "https://storage.test/produtos/1_10.jpg?"

    async def upload(self, chave: str, dados: bytes, opcoes: dict) -> Any:
        await asyncio.sleep(0)
        self.opcoes.append(dict(opcoes))
        # Reproduz a mutação específica do storage3 0.8.0.
        opcoes["x-upsert"] = opcoes.pop("upsert")
        self.objetos[chave] = dados
        if self.perder_resposta:
            self.perder_resposta = False
            raise TimeoutError("segredo-fake-no-storage")
        return SimpleNamespace(status_code=200)

    async def get_public_url(self, chave: str) -> Any:
        await asyncio.sleep(0)
        return self.url

    async def remove(self, chaves: list[str]) -> list[dict]:
        await asyncio.sleep(0)
        for chave in chaves:
            self.objetos.pop(chave, None)
        return []


class TestMidiaECliente(unittest.IsolatedAsyncioTestCase):
    async def test_upload_idempotente_async_opcoes_novas_e_remocao(self) -> None:
        bucket = BucketFake()
        cliente = SimpleNamespace(storage=SimpleNamespace(from_=lambda nome: bucket))
        midia = ArmazenamentoSupabase(cliente)
        bucket.perder_resposta = True
        with self.assertRaises(TimeoutError):
            await midia.enviar("1_10.jpg", b"jpeg")
        url = await midia.enviar("1_10.jpg", b"jpeg")
        self.assertEqual(url, bucket.url)
        self.assertEqual(bucket.objetos, {"1_10.jpg": b"jpeg"})
        self.assertTrue(all(opcao["upsert"] == "true" for opcao in bucket.opcoes))
        await midia.remover("1_10.jpg")
        await midia.remover("1_10.jpg")
        self.assertEqual(bucket.objetos, {})

    async def test_midia_rejeita_arquivo_caminho_e_url_incompleta(self) -> None:
        bucket = BucketFake()
        cliente = SimpleNamespace(storage=SimpleNamespace(from_=lambda nome: bucket))
        midia = ArmazenamentoSupabase(cliente)
        with self.assertRaises(TypeError):
            await midia.enviar("1_10.jpg", "caminho.jpg")
        with self.assertRaises(ValueError):
            await midia.enviar("../1_10.jpg", b"jpeg")
        bucket.url = {"publicUrl": "formato-incorreto"}
        with self.assertRaisesRegex(RuntimeError, "URL pública ausente"):
            await midia.enviar("1_10.jpg", b"jpeg")

    async def test_midia_timeout_e_upload_incompleto_propagam(self) -> None:
        bucket = BucketFake()
        cliente = SimpleNamespace(storage=SimpleNamespace(from_=lambda nome: bucket))
        midia = ArmazenamentoSupabase(cliente, timeout=0.001)
        with patch.object(bucket, "upload", new=AsyncMock(return_value=None)):
            with self.assertRaisesRegex(RuntimeError, "sem confirmação"):
                await midia.enviar("1_10.jpg", b"jpeg")

        async def upload_lento(*args: Any) -> Any:
            await asyncio.sleep(1)

        with patch.object(bucket, "upload", side_effect=upload_lento):
            with self.assertRaises(TimeoutError):
                await midia.enviar("1_10.jpg", b"jpeg")

    async def test_fabrica_tardia_com_timeouts_sem_ambiente(self) -> None:
        cliente = SimpleNamespace(auth=SimpleNamespace(_http_client=SimpleNamespace(timeout=None)))
        sdk = ModuleType("supabase")
        sdk.AsyncClientOptions = lambda **opcoes: SimpleNamespace(**opcoes)
        sdk.acreate_client = AsyncMock(return_value=cliente)
        with patch.dict("sys.modules", {"supabase": sdk}):
            criado = await criar_cliente("https://fake.test", "chave-fake", 2, 7)
        self.assertIs(criado, cliente)
        argumentos = sdk.acreate_client.call_args
        self.assertEqual(argumentos.args, ("https://fake.test", "chave-fake"))
        opcoes = argumentos.kwargs["options"]
        self.assertEqual(opcoes.postgrest_client_timeout, 2)
        self.assertEqual(opcoes.storage_client_timeout, 7)
        self.assertFalse(opcoes.auto_refresh_token)
        self.assertFalse(opcoes.persist_session)
        self.assertEqual(cliente.auth._http_client.timeout, 2)

    async def test_shutdown_fecha_todos_mesmo_se_um_falha(self) -> None:
        postgrest = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("falha fake")))
        storage = SimpleNamespace(aclose=AsyncMock())
        auth = SimpleNamespace(close=AsyncMock())
        cliente = SimpleNamespace(_postgrest=postgrest, _storage=storage, auth=auth)
        with self.assertRaises(RuntimeError):
            await fechar_cliente(cliente)
        postgrest.aclose.assert_awaited_once()
        storage.aclose.assert_awaited_once()
        auth.close.assert_awaited_once()

    async def test_shutdown_nao_instancia_servicos_lazy(self) -> None:
        class ClienteLazy:
            _postgrest = None
            _storage = None
            auth = SimpleNamespace(close=AsyncMock())

            @property
            def storage(self) -> Any:
                raise AssertionError("Storage lazy não deveria ser criado no encerramento")

            @property
            def postgrest(self) -> Any:
                raise AssertionError("PostgREST lazy não deveria ser criado no encerramento")

        await fechar_cliente(ClienteLazy())
        ClienteLazy.auth.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
