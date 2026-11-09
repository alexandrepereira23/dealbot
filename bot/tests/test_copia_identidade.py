"""Cópias sintéticas, sem defaults comerciais nem acesso à rede."""

import copy
import hashlib
import importlib.util
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from src.extractor import extrair_detalhado
from src.identidade import identificar
from src.telegram import Telegram


AMAZON = "https://www.amazon.com.br/dp/B012345678?smid=SELLER1"
ML = "https://produto.mercadolivre.com.br/MLB-1234567890"
TEXTO = "Notebook 16 GB\nPor R$ 2.499,90 no Pix\n"
DATA = datetime(2026, 1, 1, tzinfo=timezone.utc)
TEM_TELETHON = importlib.util.find_spec("telethon") is not None


def envelope(texto, canal=-100111, **campos):
    return Telegram.envelope(SimpleNamespace(id=1, date=DATA, message=texto, **campos), canal, "sintetico")


def da_mensagem(texto, url_resolvida=None, canal=-100111):
    mensagem = envelope(texto, canal)
    produto = extrair_detalhado(mensagem.texto, mensagem.contexto).produto
    assert produto is not None
    return identificar(produto, mensagem.texto, mensagem.contexto, url_resolvida)


class CopiaIdentidadeTests(unittest.TestCase):
    def identificar(self, link=ML, texto=None, contexto=None, preco=2499.90, **produto):
        return identificar({"link": link, "preco": preco, **produto},
                           TEXTO + link if texto is None else texto, contexto)

    def copia(self, **opcoes):
        resultado = self.identificar(**opcoes)
        self.assertIsNotNone(resultado.get("copia"))
        return resultado["copia"]

    def test_ml_real_adaptador_sem_contexto_comercial(self):
        a = da_mensagem(TEXTO + ML, canal=-100111)
        b = da_mensagem(TEXTO + ML, canal=-100222)
        self.assertIsNone(a["chave"])
        self.assertIsNone(b["chave"])
        self.assertEqual(a["copia"], b["copia"])
        self.assertEqual(a["copia"]["comparacao"]["preco_centavos"], 249990)
        self.assertEqual(a["componentes"]["campos"]["vendedor"]["estado"], "desconhecido")

    def test_amazon_tag_real_adaptador_sem_contexto_comercial(self):
        a = da_mensagem(TEXTO + AMAZON + "&tag=canal-a-20")
        b = da_mensagem(TEXTO + AMAZON + "&tag=canal-b-20", canal=-100222)
        self.assertEqual(a["copia"], b["copia"])
        self.assertIsNone(a["chave"])
        self.assertEqual(a["copia"]["comparacao"]["destino"]["query"], "smid=SELLER1")

    def test_encurtadores_so_convergem_com_destino_verificado(self):
        for link in ("https://amzn.to/DealA", "https://amzn.to/DealB"):
            self.assertNotIn("copia", da_mensagem(TEXTO + link))
        a = da_mensagem(TEXTO + "https://amzn.to/DealA", AMAZON + "&tag=canal-a-20")
        b = da_mensagem(TEXTO + "https://amzn.to/DealB", AMAZON + "&tag=canal-b-20")
        self.assertEqual(a["copia"], b["copia"])
        self.assertIsNone(a["chave"])

    def test_estrutura_aditiva_hash_canonico_e_json(self):
        r = self.identificar()
        self.assertEqual(r["versao"], 2)
        c = r["copia"]
        self.assertEqual(c["versao"], 1)
        canonico = json.dumps(c["comparacao"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(c["chave"], hashlib.sha256(canonico.encode()).hexdigest())
        self.assertEqual(json.loads(json.dumps(r)), r)

    def test_mesmo_titulo_preco_outro_produto_nao_e_copia(self):
        a = self.copia()
        b = self.copia(link=ML.replace("1234567890", "9876543210"))
        self.assertNotEqual(a["chave"], b["chave"])

    def test_preco_atual_obrigatorio_finito_exato_inclusive_zero(self):
        for preco in (None, True, -1, float("nan"), float("inf"), "NaN", "2.499,90", 1.001):
            with self.subTest(preco=preco):
                self.assertNotIn("copia", self.identificar(preco=preco))
        self.assertEqual(self.copia(preco=0)["comparacao"]["preco_centavos"], 0)
        self.assertNotEqual(self.copia(preco=100)["chave"], self.copia(preco=99)["chave"])

    def test_post_inteiro_nao_apenas_titulo_e_preco(self):
        base = self.copia()
        for condicao in ("Vendedor: Loja A", "SKU: ABC", "Variante: azul", "Quantidade: 2",
                         "Kit: duplo", "Estado: usado", "Cupom: AbC10", "somente app",
                         "Frete para SP", "Exclusivo Prime", "sem cashback", "128 GB",
                         "Pagamento: boleto", "Assinatura: mensal", "Elegibilidade: novos clientes"):
            with self.subTest(condicao=condicao):
                outro = self.copia(texto=TEXTO + ML + "\n" + condicao)
                self.assertNotEqual(base["chave"], outro["chave"])

    def test_normalizacao_somente_crlf_case_espacos_e_unicode_preservados(self):
        base = self.copia()
        self.assertEqual(base, self.copia(texto=(TEXTO + ML).replace("\n", "\r\n")))
        for texto in ((TEXTO + ML).replace("Notebook", "notebook"),
                      (TEXTO + ML).replace("16 GB", "16  GB"), TEXTO + ML + "\n",
                      "é\n" + TEXTO + ML, "e\u0301\n" + TEXTO + ML):
            self.assertNotEqual(base["chave"], self.copia(texto=texto)["chave"])
        self.assertNotEqual(self.copia(texto="é\n" + TEXTO + ML)["chave"],
                            self.copia(texto="e\u0301\n" + TEXTO + ML)["chave"])

    def test_smid_linkcode_origem_e_path_preservados(self):
        base = self.copia(link=AMAZON + "&linkCode=AbC")
        for url in ((AMAZON + "&linkCode=abc"), AMAZON.replace("SELLER1", "SELLER2") + "&linkCode=AbC",
                    AMAZON.replace("www.", "") + "&linkCode=AbC",
                    AMAZON.replace("https:", "http:") + "&linkCode=AbC",
                    AMAZON.replace("?", "/?") + "&linkCode=AbC",
                    AMAZON.replace(".br/", ".br:443/") + "&linkCode=AbC"):
            with self.subTest(url=url):
                self.assertNotEqual(base["chave"], self.copia(link=url)["chave"])

    def test_url_desconhecida_query_fragmento_nunca_apagados(self):
        for link in (AMAZON + "&ref=A", AMAZON + "&Tag=A", AMAZON + "&utm_source=A", AMAZON + "#",
                     AMAZON + "&smid=SELLER1", AMAZON + "&tag=", ML + "?variation_id=1",
                     ML + "#variante", "https://loja.test/A", "https://www.amazon.com/dp/B012345678"):
            with self.subTest(link=link):
                self.assertNotIn("copia", self.identificar(link=link))

    def test_resolucao_nao_apaga_query_fragmento_ou_destino_original(self):
        for link in (AMAZON + "&unknown=A", AMAZON + "#variante", "https://amzn.to/DealA#variante",
                     "https://amzn.to/DealA?sku=A", AMAZON.replace("SELLER1", "SELLER2"),
                     AMAZON + "&linkCode=AbC", AMAZON.replace("B012345678", "B999999999")):
            with self.subTest(link=link):
                self.assertNotIn("copia", identificar({"link": link, "preco": 10}, TEXTO + link,
                                                     url_resolvida=AMAZON))

    def test_destino_resolvido_invalido_nao_cria_copia(self):
        for destino in ("https://loja.test/A", AMAZON + "&unknown=A", AMAZON + "#variante"):
            self.assertNotIn("copia", identificar({"link": "https://amzn.to/DealA", "preco": 10},
                                                 TEXTO + "https://amzn.to/DealA", url_resolvida=destino))

    def test_sem_texto_sem_link_no_post_e_url_sozinha_insuficientes(self):
        for texto in ("", "Notebook R$ 2.499,90", ML, ML + "\nhttps://outro.test/A"):
            with self.subTest(texto=texto):
                self.assertNotIn("copia", self.identificar(texto=texto))

    def test_multiplas_ocorrencias_mesmo_link_ambiguas(self):
        self.assertNotIn("copia", self.identificar(texto=TEXTO + ML + "\n" + ML))

    def test_link_selecionado_nao_substitui_prefixo_de_outra_url(self):
        self.assertNotIn("copia", self.identificar(texto=TEXTO + ML + "?variation=1"))
        self.assertNotIn("copia", self.identificar(texto=TEXTO + ML + "0"))

    def test_outros_links_inclusive_tags_ficam_intactos(self):
        a = self.copia(link=AMAZON + "&tag=a", texto=TEXTO + AMAZON + "&tag=a\n" + ML)
        b = self.copia(link=AMAZON + "&tag=b", texto=TEXTO + AMAZON + "&tag=b\n" + ML)
        self.assertEqual(a, b)
        self.assertIn(ML, a["comparacao"]["conteudo"])
        self.assertNotEqual(a["chave"], self.copia(link=AMAZON + "&tag=b", texto=TEXTO + AMAZON
                            + "&tag=b\n" + ML.replace("1234567890", "9876543210"))["chave"])
        self.assertNotEqual(self.copia(texto=TEXTO + ML + "\n" + AMAZON + "&tag=a")["chave"],
                            self.copia(texto=TEXTO + ML + "\n" + AMAZON + "&tag=b")["chave"])

    def test_contexto_parcial_e_campos_futuros_nao_sao_ignorados(self):
        base = self.copia()
        for campo, valor in (("vendedor", "SELLER1"), ("sku", "AbC"), ("variante", "128GB"),
                             ("cupom", "AbC10"), ("prazo_especial", "somente hoje"), ("sku", None)):
            with self.subTest(campo=campo, valor=valor):
                outro = self.copia(contexto={"identidade": {campo: valor}})
                self.assertNotEqual(base["chave"], outro["chave"])
        a = self.copia(contexto={"identidade": {"prazo_especial": "hoje"}})
        b = self.copia(contexto={"identidade": {"prazo_especial": "amanha"}})
        self.assertNotEqual(a["chave"], b["chave"])

    def test_proveniencia_nao_participa_da_copia(self):
        a = self.copia(contexto={"identidade": {"sku": {"estado": "conhecido", "valor": "AbC", "fonte": "canal A"}}})
        b = self.copia(contexto={"identidade": {"sku": {"estado": "conhecido", "valor": "AbC", "fonte": "cache B"}}})
        self.assertEqual(a, b)

    def test_declaracao_invalida_inclusive_futura_desabilita_copia(self):
        for identidade in ([], {"sku": "desconhecido"}, {"sku": {"estado": "conhecido"}},
                           {"futuro": {"estado": "conhecido", "valor": "A", "alternativa": "B"}},
                           {"quantidade": "0"}, {"vendedor": {"estado": "nao_aplicavel", "motivo": "prova"}}):
            with self.subTest(identidade=identidade):
                self.assertNotIn("copia", self.identificar(contexto={"identidade": identidade}))

    def test_conflito_url_texto_contexto_cupom_desabilita_copia(self):
        casos = [dict(link=AMAZON, contexto={"identidade": {"vendedor": "SELLER2"}}),
                 dict(contexto={"identidade": {"produto": "MLB-9876543210"}}),
                 dict(texto=TEXTO + ML + "\nSKU: A", contexto={"identidade": {"sku": "B"}}),
                 dict(texto=TEXTO + ML + "\nCupom: AbC10", cupom="OUTRO10"),
                 dict(texto=TEXTO + ML + "\nVendedor: A\nVendedor: B")]
        for caso in casos:
            with self.subTest(caso=caso):
                self.assertNotIn("copia", self.identificar(**caso))

    def test_cupom_extraido_sem_texto_nao_pode_ser_ignorado(self):
        self.assertNotEqual(self.copia(cupom="AbC10")["chave"], self.copia(cupom="abc10")["chave"])

    def test_contexto_codigo_exclusao_e_evidencia_futura_preservados(self):
        texto = TEXTO + ML + "\nAbC10"
        base = self.copia(texto=texto)
        for contexto in ({"codigos": [{"offset": texto.index("AbC10"), "length": 5}]},
                         {"exclusoes": [{"offset": 0, "length": 8}]},
                         {"evidencias": {"condicao_futura": "somente hoje"}}):
            self.assertNotEqual(base["chave"], self.copia(texto=texto, contexto=contexto)["chave"])

    def test_entidade_visivel_mesmo_span_nao_e_ambigua_e_offsets_ajustados(self):
        resultados = []
        for tag in ("a", "canal-com-nome-longo"):
            link = AMAZON + "&tag=" + tag
            texto = TEXTO + link + "\nAbC10"
            span = {"offset": len(TEXTO), "length": len(link)}
            contexto = {"links": [{"url": link, "origem": "entidade", "rotulo": link, **span}],
                        "exclusoes": [span], "codigos": [{"offset": texto.index("AbC10"), "length": 5}]}
            resultados.append(self.copia(link=link, texto=texto, contexto=contexto))
        self.assertEqual(*resultados)

    def test_entidade_oculta_preserva_rotulo_e_outros_links(self):
        texto = TEXTO + "Comprar aqui"
        def copia(link, rotulo="Comprar aqui", extra=ML):
            contexto = {"links": [{"url": link, "origem": "entidade", "rotulo": rotulo,
                                   "offset": len(TEXTO), "length": len(rotulo)},
                                  {"url": extra, "origem": "botao", "rotulo": "Regras"}]}
            return self.copia(link=link, texto=TEXTO + rotulo, contexto=contexto)
        a, b = copia(AMAZON + "&tag=a"), copia(AMAZON + "&tag=b")
        self.assertEqual(a, b)
        self.assertEqual(a["comparacao"]["conteudo"], texto)
        self.assertNotEqual(a["chave"], copia(AMAZON + "&tag=b", rotulo="Somente Prime")["chave"])
        self.assertNotEqual(a["chave"], copia(AMAZON + "&tag=b", extra=ML + "?regra=A")["chave"])

    def test_botao_preserva_rotulo_ordem_outros_botoes_e_metadados(self):
        def contexto(link, rotulo="Comprar", outro=ML, inverter=False):
            links = [{"url": link, "origem": "botao", "rotulo": rotulo},
                     {"url": outro, "origem": "botao", "rotulo": "Regras"}]
            return {"links": list(reversed(links)) if inverter else links}
        a = self.copia(link=AMAZON + "&tag=a", texto=TEXTO, contexto=contexto(AMAZON + "&tag=a"))
        b = self.copia(link=AMAZON + "&tag=b", texto=TEXTO, contexto=contexto(AMAZON + "&tag=b"))
        self.assertEqual(a, b)
        for opcoes in ({"rotulo": "Somente app"}, {"outro": ML + "?regra=A"}, {"inverter": True}):
            outro = self.copia(link=AMAZON, texto=TEXTO, contexto=contexto(AMAZON, **opcoes))
            self.assertNotEqual(a["chave"], outro["chave"])

    def test_multiplas_ligacoes_e_spans_invalidos_desabilitam_copia(self):
        botao = {"url": ML, "origem": "botao", "rotulo": "Comprar"}
        for texto, links in ((TEXTO, [botao, botao]), (TEXTO + ML, [botao]),
                             (TEXTO + "Comprar", [{"url": ML, "origem": "entidade", "rotulo": "Comprar", "offset": 9999, "length": 7}]),
                             (TEXTO + "Comprar", [{"url": ML, "origem": "entidade", "rotulo": "Outro", "offset": len(TEXTO), "length": 7}])):
            self.assertNotIn("copia", self.identificar(texto=texto, contexto={"links": links}))

    def test_entradas_nao_mutadas(self):
        link = AMAZON + "&tag=a"
        produto = {"link": link, "preco": 2499.90, "cupom": None}
        contexto = {"links": [{"url": link, "origem": "botao", "rotulo": "Comprar"}],
                    "identidade": {"sku": {"estado": "conhecido", "valor": "A", "fonte": "local"}}}
        antes = copy.deepcopy((produto, contexto))
        self.assertIn("copia", identificar(produto, TEXTO, contexto))
        self.assertEqual((produto, contexto), antes)


@unittest.skipUnless(TEM_TELETHON, "Telethon fixado necessário para entidades reais")
class CopiaTelegramEntitiesTests(unittest.TestCase):
    def mensagens(self, tipo):
        from telethon.tl.types import (KeyboardButtonRow, KeyboardButtonUrl, MessageEntityTextUrl,
                                      MessageEntityUrl, ReplyInlineMarkup)
        resultados = []
        for tag in ("a", "canal-longo-b"):
            link = AMAZON + "&tag=" + tag
            texto = "🚀 " + TEXTO
            campos = {}
            if tipo == "botao":
                campos["reply_markup"] = ReplyInlineMarkup(rows=[KeyboardButtonRow(buttons=[
                    KeyboardButtonUrl(text="Comprar", url=link), KeyboardButtonUrl(text="Regras", url=ML)])])
            else:
                rotulo = link if tipo == "visivel" else "Comprar 🛒 aqui"
                inicio = len(texto.encode("utf-16-le")) // 2
                texto += rotulo
                entidade = MessageEntityUrl if tipo == "visivel" else MessageEntityTextUrl
                opcoes = {} if tipo == "visivel" else {"url": link}
                campos["entities"] = [entidade(offset=inicio, length=len(rotulo.encode("utf-16-le")) // 2, **opcoes)]
            msg = envelope(texto, **campos)
            produto = extrair_detalhado(msg.texto, msg.contexto).produto
            self.assertIsNotNone(produto)
            resultados.append(identificar(produto, msg.texto, msg.contexto))
        return resultados

    def test_entidade_url_visivel_adapter_real(self):
        a, b = self.mensagens("visivel")
        self.assertIsNotNone(a.get("copia"))
        self.assertEqual(a["copia"], b["copia"])

    def test_entidade_oculta_adapter_real(self):
        a, b = self.mensagens("oculta")
        self.assertIsNotNone(a.get("copia"))
        self.assertEqual(a["copia"], b["copia"])

    def test_botoes_adapter_real(self):
        a, b = self.mensagens("botao")
        self.assertIsNotNone(a.get("copia"))
        self.assertEqual(a["copia"], b["copia"])


if __name__ == "__main__":
    unittest.main()
