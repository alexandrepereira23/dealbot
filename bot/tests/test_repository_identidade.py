"""Fronteira HTTP fake: não substitui testes de transações Postgres."""

import unittest
from types import SimpleNamespace

from src.repository_identidade import RepositorioIdentidade


class ClienteRPC:
    def __init__(self):
        self.chamadas = []
        self.resposta = [{"id": 9, "status": "novo", "foto_url": None}]
        self.erro = None

    def rpc(self, nome, params):
        self.chamadas.append((nome, params))

        async def execute():
            if self.erro:
                raise self.erro
            return SimpleNamespace(data=self.resposta)
        return SimpleNamespace(execute=execute)

    def table(self, nome):
        raise AssertionError("Não pode cair em SELECT/upsert por título/hash legado")


class TestRepositorioIdentidade(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cliente = ClienteRPC()
        self.repo = RepositorioIdentidade(self.cliente)
        self.job = {"canal_id": -100123, "msg_id": 1, "remoto_canal": "sintetico",
            "data_origem": "2026-11-05T10:00:00Z", "recebido_em": 1793872800,
            "tem_foto": True, "texto": "mensagem sintética", "hash": "a" * 32}

    async def test_registro_atomico_projeta_produto_sem_diagnostico(self):
        identidade = {"versao": 2, "chave": None, "componentes": {}, "motivo": "incerto", "enriquecer": True}
        r = await self.repo.salvar_identificada(self.job, {"titulo": "SSD", "preco": 0,
            "diagnostico": {"texto": "privado"}, "link": "https://amzn.to/AbC"}, identidade, 48)
        self.assertEqual((r.produto_id, r.status), (9, "novo"))
        nome, params = self.cliente.chamadas[0]
        self.assertEqual(nome, "oferta_registrar")
        self.assertEqual(params["p_evento"]["canal_id"], -100123)
        self.assertTrue(params["p_evento"]["enriquecer"])
        self.assertEqual(params["p_produto"]["preco"], 0)
        self.assertNotIn("diagnostico", params["p_produto"])
        self.assertEqual(params["p_identidade"], identidade)

    async def test_schema_indisponivel_nao_faz_fallback_legado(self):
        self.cliente.erro = RuntimeError("PGRST202")
        with self.assertRaisesRegex(RuntimeError, "PGRST202"):
            await self.repo.salvar_identificada(self.job, {"titulo": "SSD"}, {"versao": 2}, 48)
        self.assertEqual(len(self.cliente.chamadas), 1)

    async def test_resposta_incompleta_nao_finge_commit_confirmado(self):
        for resposta in ([], [{"id": 9, "status": "novo"}], [{"id": 0, "status": "novo", "foto_url": None}]):
            self.cliente.resposta = resposta
            with self.assertRaises(RuntimeError):
                await self.repo.salvar_identificada(self.job, {"titulo": "SSD"}, {"versao": 2}, 48)

    async def test_enriquecimento_tem_checkpoint_proprio_nao_envia_decisao(self):
        self.cliente.resposta = [{"id": 2, "status": "fundido", "foto_url": "https://storage.invalid/9.jpg"}]
        r = await self.repo.enriquecer(self.job, {"versao": 2, "chave": "b" * 64})
        self.assertEqual(r.produto_id, 2)
        nome, params = self.cliente.chamadas[-1]
        self.assertEqual(nome, "oferta_enriquecer")
        self.assertEqual(set(params), {"p_canal_id", "p_msg_id", "p_identidade"})

    async def test_busca_alias_e_foto_sao_operacoes_remotas_canonicas(self):
        self.cliente.resposta = [{"id": 2, "foto_url": "https://storage.invalid/9.jpg"}]
        self.assertEqual((await self.repo.buscar_produto(9))["id"], 2)
        self.assertEqual(self.cliente.chamadas[-1], ("oferta_buscar", {"p_id": 9}))
        self.cliente.resposta = [{"status": "existente"}]
        self.assertEqual(await self.repo.vincular_foto(9, "https://storage.invalid/10.jpg"), "existente")

    async def test_reserva_nao_confunde_foto_em_uso_com_permissao_remocao(self):
        self.cliente.resposta = [{"permitido": False}]
        self.assertFalse(await self.repo.reservar_remocao("https://storage.invalid/9.jpg"))
        self.cliente.resposta = [{"permitido": "false"}]
        with self.assertRaises(RuntimeError):
            await self.repo.reservar_remocao("https://storage.invalid/9.jpg")

    async def test_confirmacao_de_evento_nao_usa_janela_temporal(self):
        self.cliente.resposta = [{"status": "confirmado"}]
        await self.repo.confirmar_evento(self.job)
        self.assertEqual(self.cliente.chamadas[-1], ("oferta_confirmar", {"p_canal_id": -100123, "p_msg_id": 1}))

    async def test_confirmacao_incompleta_nao_libera_referencia_local(self):
        for resposta in ([], [{"status": "ausente"}]):
            self.cliente.resposta = resposta
            with self.assertRaises(RuntimeError):
                await self.repo.confirmar_evento(self.job)
            with self.assertRaises(RuntimeError):
                await self.repo.confirmar_remocao("https://storage.invalid/9.jpg")

    async def test_foto_com_remocao_reservada_nao_reabre_objeto(self):
        self.cliente.resposta = [{"status": "remocao_reservada"}]
        self.assertEqual(await self.repo.vincular_foto(9, "https://storage.invalid/9.jpg"), "removida")

    async def test_legado_envia_hash_congelado_e_aliases_sem_identidade_nova(self):
        job = {**self.job, "produto_id": 9}
        await self.repo.salvar_legada(job, {"titulo": "Antigo", "preco": 0}, "c"*32, ["@antigo"])
        nome, dados = self.cliente.chamadas[-1]
        self.assertEqual(nome, "oferta_legado_registrar")
        self.assertEqual(dados["p_hash"], "c"*32)
        self.assertEqual(dados["p_evento"]["produto_id"], 9)
        self.assertIn("@antigo", dados["p_evento"]["aliases"])
        self.assertNotIn("p_identidade", dados)

    async def test_reutilizado_sem_mudanca_de_preco_continua_duplicata(self):
        self.cliente.resposta = [{"id": 9, "status": "reutilizado", "foto_url": None}]
        self.assertEqual((await self.repo.salvar_identificada(self.job, {"titulo":"X"}, {"versao":2}, 48)).status, "duplicado")

    async def test_username_reutilizado_nao_substitui_par_numerico_nas_duas_rpcs(self):
        for canal in (-100123, -100456):
            job = {**self.job, "canal_id": canal, "produto_id": None}
            # canal_id de produto não é input público; só o evento é autoridade.
            await self.repo.salvar_identificada(job, {"titulo": "X", "canal_id": 999}, {"versao": 2}, 48)
            await self.repo.salvar_legada(job, {"titulo": "Congelado", "canal_id": 999}, "c"*32, [])
        for nome, dados in self.cliente.chamadas:
            self.assertIn(nome, {"oferta_registrar", "oferta_legado_registrar"})
            self.assertEqual(dados["p_evento"]["msg_id"], 1)
            self.assertEqual(dados["p_evento"]["canal_origem"], "sintetico")
            self.assertNotIn("canal_id", dados["p_produto"])
        self.assertEqual([p["p_evento"]["canal_id"] for _, p in self.cliente.chamadas],
                         [-100123, -100123, -100456, -100456])

    async def test_prontidao_incompativel_nao_libera_gate_nem_recorre_a_tabelas(self):
        self.cliente.erro = RuntimeError("Etapa 3: índice incompatível")
        with self.assertRaisesRegex(RuntimeError, "índice incompatível"):
            await self.repo.legados_prontos()
        self.assertEqual(self.cliente.chamadas, [("oferta_legado_pronto", {})])
        self.cliente.erro = None
        self.cliente.resposta = []
        with self.assertRaisesRegex(RuntimeError, "prontidao_legada_nao_confirmada"):
            await self.repo.legados_prontos()
