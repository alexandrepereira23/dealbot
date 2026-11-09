"""Fixtures EXCLUSIVAMENTE sintéticas; não são amostras de anúncios reais."""

import copy
import hashlib
import json
import unittest

from src.identidade import identificar, normalizar_url


AMAZON = "https://www.amazon.com.br/dp/B012345678"
ML = "https://produto.mercadolivre.com.br/MLB-1234567890"


def nao_aplicavel(motivo="Declarado explicitamente na fixture da oferta selecionada"):
    return {"estado": "nao_aplicavel", "motivo": motivo}


def contexto_completo(ml=False):
    """Não são defaults de produção; cada valor é prova sintética EXPLÍCITA."""
    return {"identidade": {
        "anuncio": "MLB-1234567890" if ml else nao_aplicavel(),
        "vendedor": "SELLER1", "sku": "SKU-A", "variante": "selecionada-128-preto",
        "estado": "novo", "quantidade": 1, "kit": "unitario",
        "elegibilidade": "todos os clientes", "pagamento": "pix",
        "cupom": nao_aplicavel("A oferta declara explicitamente sem cupom"),
        "restricoes": "sem outras restricoes conforme declaracao explicita",
        "frete": "gratis para todo Brasil", "assinatura": nao_aplicavel(),
    }}


class NormalizacaoEtapa3Tests(unittest.TestCase):
    def test_so_esquema_e_host_mudam(self):
        url = "HTTPS://WWW.AMAZON.COM.BR:443/AbC/%2f/?X=AbC&X=&x&X=2#ToKen"
        self.assertEqual(normalizar_url(url),
                         "https://www.amazon.com.br:443/AbC/%2f/?X=AbC&X=&x&X=2#ToKen")

    def test_preserva_todas_distincoes_semanticas(self):
        pares = [
            ("/AbC", "/abc"), ("/A", "/A/"), ("/A?", "/A"),
            ("/A#", "/A"), ("/A?X=1", "/A?x=1"), ("/A?k=Ab", "/A?k=ab"),
            ("/A?k=1&k=2", "/A?k=2&k=1"), ("/A?k=", "/A?k"),
            ("/A?k=1&", "/A?k=1"), ("/A/%2F", "/A/%2f"),
            ("/A?k=%41", "/A?k=A"), ("/A#AbC", "/A#abc"),
        ]
        for a, b in pares:
            with self.subTest(a=a, b=b):
                self.assertNotEqual(normalizar_url("https://x.test" + a),
                                    normalizar_url("https://x.test" + b))

    def test_sem_tracking_universal(self):
        url = "https://x.test/AbC?ref=A&tag=B&aff=C&smid=D&linkCode=E&utm_source=F#AbC"
        self.assertEqual(normalizar_url(url), url)

    def test_nao_muda_esquema_dominio_porta_ou_userinfo(self):
        for url in ("http://x.test/A", "https://x.test:443/A", "https://y.test/A",
                    "HTTPS://User:ToKen@X.TEST/AbC", "https://x.test/A?#"):
            self.assertEqual(normalizar_url(url), url)

    def test_invalida_intacta(self):
        for url in ("https://X.TEST/\nA", " https://X.TEST/A", "token:AbC", "https://X%2eTEST/A"):
            self.assertEqual(normalizar_url(url), url)
        with self.assertRaises(TypeError):
            normalizar_url(None)


class IdentidadeEtapa3Tests(unittest.TestCase):
    def forte(self, link=AMAZON, contexto=None, **produto):
        return identificar({"link": link, **produto}, contexto=contexto or contexto_completo())

    def test_positivo_amazon_completo_tracking_restrito(self):
        a = self.forte(AMAZON + "?smid=SELLER1&tag=canal-a-20&linkCode=ll1", preco=100)
        b = self.forte(AMAZON + "?tag=canal-b-20&smid=SELLER1&linkCode=ll1", preco=50)
        self.assertEqual(a["motivo"], "identidade_forte")
        self.assertRegex(a["chave"], r"^[a-f0-9]{64}$")
        self.assertEqual(a["chave"], b["chave"])
        self.assertEqual(a["componentes"]["comparacao"], b["componentes"]["comparacao"])

    def test_linkcode_comparacao_exata_nao_equivalencia_inventada(self):
        a = self.forte(AMAZON + "?linkCode=ll1")
        b = self.forte(AMAZON + "?linkCode=ll2")
        self.assertIsNotNone(a["chave"])
        self.assertIsNotNone(b["chave"])
        self.assertNotEqual(a["chave"], b["chave"])

    def test_positivo_ml_completo_anuncio_variante_seller(self):
        a = self.forte(ML, contexto_completo(True), preco=0)
        b = self.forte(ML, contexto_completo(True), preco=None)
        self.assertIsNotNone(a["chave"])
        self.assertEqual(a["chave"], b["chave"])
        self.assertEqual(a["componentes"]["campos"]["anuncio"]["valor"], "MLB-1234567890")

    def test_hash_do_json_de_comparacao_nao_das_evidencias(self):
        r = self.forte()
        serializado = json.dumps(r["componentes"]["comparacao"], sort_keys=True,
                                separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(r["chave"], hashlib.sha256(serializado.encode()).hexdigest())
        self.assertEqual(json.loads(json.dumps(r)), r)

    def test_preco_titulo_foto_nao_sao_identidade(self):
        a = self.forte(preco=12, titulo="Produto A", foto_url="A")
        b = self.forte(preco=None, titulo="Produto B", foto_url="B", preco_original=500)
        self.assertEqual(a["chave"], b["chave"])
        for produto in ({"titulo": "Igual", "preco": 12},
                        {"link": "https://amzn.to/AbC", "titulo": "Igual", "preco": 12}):
            self.assertIsNone(identificar(produto)["chave"])

    def test_cada_condicao_obrigatoria_omitida_impede_chave(self):
        for campo in contexto_completo()["identidade"]:
            c = contexto_completo()
            del c["identidade"][campo]
            with self.subTest(campo=campo):
                r = identificar({"link": AMAZON}, contexto=c)
                self.assertIsNone(r["chave"])
                self.assertIn(campo, r["componentes"]["desconhecidos"])

    def test_asin_ou_smid_sozinhos_nao_confirmam(self):
        for link in (AMAZON, AMAZON + "?smid=SELLER1", ML):
            r = identificar({"link": link})
            self.assertIsNone(r["chave"])
            self.assertEqual(r["componentes"]["campos"]["vendedor"]["estado"], "desconhecido")

    def test_diferencas_comprovadas_separam_todas_condicoes(self):
        base = self.forte()
        alteracoes = {
            "anuncio": "OUTRO", "vendedor": "SELLER2", "sku": "SKU-B",
            "variante": "selecionada-256-azul", "estado": "usado", "quantidade": 2,
            "kit": "2 pecas", "elegibilidade": "primeira compra", "pagamento": "boleto",
            "cupom": "AbC10", "restricoes": "somente app", "frete": "pago",
            "assinatura": "mensal", "cor": "azul", "capacidade": "256GB",
            "tamanho": "G", "voltagem": "220V",
        }
        for campo, valor in alteracoes.items():
            c = contexto_completo()
            c["identidade"][campo] = valor
            with self.subTest(campo=campo):
                r = self.forte(contexto=c)
                self.assertIsNotNone(r["chave"])
                self.assertNotEqual(r["chave"], base["chave"])
                self.assertNotEqual(r["componentes"]["comparacao"], base["componentes"]["comparacao"])

    def test_outro_id_loja_path_esquema_porta_nao_colapsam(self):
        base = self.forte()["chave"]
        for link in (AMAZON.replace("B012345678", "B987654321"),
                     AMAZON.replace("www.", ""), AMAZON.replace("https:", "http:"),
                     AMAZON + "/", AMAZON.replace(".br/", ".br:443/"), AMAZON + "?"):
            with self.subTest(link=link):
                self.assertNotEqual(base, self.forte(link)["chave"])

    def test_queries_nao_comprovadas_fragmentos_assinaturas_negativos(self):
        for sufixo in ("?ref=A", "?aff=A", "?utm_source=A", "?linkcode=ll1", "?LinkCode=ll1",
                       "?tag=", "?tag=A&", "?smid=SELLER1&smid=SELLER1", "?smid=SELLER2",
                       "?X=1&X=&x=2", "?signature=AbC", "#A", "#", "?smid=%53ELLER1"):
            with self.subTest(sufixo=sufixo):
                r = self.forte(AMAZON + sufixo)
                self.assertIsNone(r["chave"])
                self.assertEqual(r["url_identidade"], AMAZON + sufixo)

    def test_query_ml_variacao_nao_presumida(self):
        for sufixo in ("?variation_id=1", "?seller_id=1", "?catalog_product_id=MLB1", "?tag=A"):
            self.assertIsNone(self.forte(ML + sufixo, contexto_completo(True))["chave"])

    def test_formato_host_valido_nao_significa_todos_formatos(self):
        for link in (AMAZON.replace("/dp/", "/gp/product/"), AMAZON.replace("B012345678", "b012345678"),
                     "https://www.amazon.com/dp/B012345678", ML + "-slug",
                     "https://www.mercadolivre.com.br/p/MLB12345678",
                     "https://www.amazon.com.br.evil.test/dp/B012345678",
                     "https://user:pass@www.amazon.com.br/dp/B012345678", AMAZON + "\n",
                     AMAZON.replace(".br/", ".br:444/")):
            self.assertIsNone(self.forte(link)["chave"])

    def test_conflito_contexto_url_guarda_as_duas_provas(self):
        c = contexto_completo()
        c["identidade"]["produto"] = "B999999999"
        r = self.forte(contexto=c)
        self.assertIsNone(r["chave"])
        self.assertIn("produto", r["componentes"]["conflitos"])
        self.assertEqual(len(r["componentes"]["evidencias"]["produto"]), 2)

    def test_conflito_smid_confirmacao_nao_e_apagado(self):
        r = self.forte(AMAZON + "?smid=SELLER2")
        self.assertIn("vendedor", r["componentes"]["conflitos"])
        self.assertEqual({e["valor"] for e in r["componentes"]["evidencias"]["vendedor"]},
                         {"SELLER1", "SELLER2"})

    def test_conflitos_textuais_por_nome_preservados(self):
        for rotulo, valor, campo in (("Pagamento", "boleto", "pagamento"),
                                     ("Vendedor", "SELLER2", "vendedor"),
                                     ("Variante", "outra", "variante"),
                                     ("Cupom", "AbC10", "cupom"),
                                     ("Quantidade", "2", "quantidade")):
            with self.subTest(campo=campo):
                r = identificar({"link": AMAZON}, f"{rotulo}: {valor}", contexto_completo())
                self.assertIsNone(r["chave"])
                self.assertIn(campo, r["componentes"]["conflitos"])

    def test_restricoes_livres_desconhecidas_impedem_chave(self):
        for texto in ("Somente no app", "Primeira compra", "Exclusivo Prime", "Frete para SP",
                      "128GB", "No Pix", "2 unidades", "Usado", "Cashback no clube"):
            self.assertIsNone(identificar({"link": AMAZON}, texto, contexto_completo())["chave"])

    def test_todas_condicoes_textuais_explicitas_permite_chave(self):
        c = contexto_completo()["identidade"]
        c = {k: "nao se aplica explicitamente nesta oferta" if isinstance(v, dict) else v
             for k, v in c.items()}
        rotulos = {"anuncio": "Anúncio", "sku": "SKU", "restricoes": "Restrições"}
        texto = "\n".join(f"{rotulos.get(k, k.capitalize())}: {v}" for k, v in c.items())
        r = identificar({"link": AMAZON}, texto)
        self.assertIsNotNone(r["chave"])

    def test_omissao_cupom_nao_e_sem_cupom_nem_remove(self):
        c = contexto_completo()
        del c["identidade"]["cupom"]
        antes = copy.deepcopy(c)
        r = identificar({"link": AMAZON, "cupom": None}, contexto=c)
        self.assertIsNone(r["chave"])
        self.assertEqual(r["componentes"]["campos"]["cupom"]["estado"], "desconhecido")
        self.assertEqual(c, antes)

    def test_cupom_case_sensivel_e_conflitos(self):
        a = contexto_completo()
        a["identidade"]["cupom"] = "AbC10"
        b = copy.deepcopy(a)
        b["identidade"]["cupom"] = "abc10"
        self.assertNotEqual(self.forte(contexto=a)["chave"], self.forte(contexto=b)["chave"])
        r = identificar({"link": AMAZON, "cupom": "XYZ10"}, contexto=a)
        self.assertIsNone(r["chave"])
        self.assertIn("cupom", r["componentes"]["conflitos"])

    def test_nulos_defaults_vagos_nao_aplicavel_sem_prova_invalidos(self):
        for valor in (None, "", "desconhecido", "não informado", "n/a", False,
                      "padrão", "default",
                      {"estado": "desconhecido"}, {"estado": "nao_aplicavel"},
                      {"estado": "nao_aplicavel", "motivo": "prova", "valor": "VarianteA"},
                      {"estado": "conhecido", "valor": "VarianteA", "alternativa": "VarianteB"},
                      {"estado": "conhecido", "valor": None}):
            with self.subTest(valor=valor):
                c = contexto_completo()
                c["identidade"]["variante"] = valor
                self.assertIsNone(identificar({"link": AMAZON}, contexto=c)["chave"])

    def test_vendedor_quantidade_estado_nao_podem_ser_nao_aplicaveis(self):
        for campo in ("vendedor", "quantidade", "estado"):
            c = contexto_completo()
            c["identidade"][campo] = nao_aplicavel()
            self.assertIsNone(self.forte(contexto=c)["chave"])

    def test_quantidade_precisa_ser_inteiro_positivo(self):
        for valor in (0, -1, "1.0", "2 ou 3", "01", 1.5, True):
            c = contexto_completo()
            c["identidade"]["quantidade"] = valor
            self.assertIsNone(self.forte(contexto=c)["chave"])

    def test_evidencia_nova_desconhecida_nao_e_ignorada(self):
        c = contexto_completo()
        c["identidade"]["prazo_especial"] = "restrito"
        self.assertIsNone(self.forte(contexto=c)["chave"])

    def test_original_nunca_mutado_e_resolucao_preserva_conflitos(self):
        p = {"link": "https://amzn.to/AbC", "cupom": None}
        c = contexto_completo()
        antes = copy.deepcopy((p, c))
        r = identificar(p, contexto=c, url_resolvida=AMAZON)
        self.assertEqual((p, c), antes)
        self.assertEqual(r["url_identidade"], AMAZON)
        self.assertIsNotNone(r["chave"])
        r = identificar({"link": AMAZON}, contexto=c,
                        url_resolvida=AMAZON.replace("B012345678", "B999999999"))
        self.assertIsNone(r["chave"])
        self.assertIn("produto", r["componentes"]["conflitos"])

    def test_resolucao_nao_apaga_query_ou_fragmento_incerto_original(self):
        for sufixo in ("?smid=SELLER2&unknown=A", "?smid=SELLER2&smid=SELLER1", "#VarianteA"):
            r = identificar({"link": AMAZON + sufixo}, contexto=contexto_completo(), url_resolvida=AMAZON)
            self.assertIsNone(r["chave"])
            self.assertEqual(r["componentes"]["urls"]["original"], AMAZON + sufixo)
        r = identificar({"link": "https://amzn.to/AbC#VarianteA"},
                        contexto=contexto_completo(), url_resolvida=AMAZON)
        self.assertIsNone(r["chave"])

    def test_fonte_declarada_preservada_sem_participar_do_hash(self):
        c = contexto_completo()
        c["identidade"]["vendedor"] = {"estado": "conhecido", "valor": "SELLER1", "fonte": "fixture-autorizada"}
        r = self.forte(contexto=c)
        self.assertEqual(r["componentes"]["evidencias"]["vendedor"][0]["origem_declarada"], "fixture-autorizada")
        self.assertEqual(r["chave"], self.forte()["chave"])


if __name__ == "__main__":
    unittest.main()
