import { z } from "zod";
import { ProdutoModel } from "../models/produto.model.js";
import { NaoEncontrado, RequisicaoInvalida } from "../utils/errors.js";

const listarSchema = z.object({
  categoria: z.string().max(50).optional(),
  q: z.string().max(200).optional(),
  limite: z.coerce.number().int().min(1).max(100).default(60),
  offset: z.coerce.number().int().min(0).default(0),
});
const idSchema = z.coerce.number().int().positive().max(Number.MAX_SAFE_INTEGER);
const CAMPOS_PUBLICOS = ["id", "titulo", "preco", "preco_original", "cupom", "link",
  "foto_url", "categoria", "canal_origem", "criado_em", "data_oferta",
  "preco_anterior_atualizacao", "preco_observado_em", "atualizado_em",
  "ultima_aparicao_em", "expira_em"];

function validarId(id) {
  const parsed = idSchema.safeParse(id);
  if (!parsed.success) throw RequisicaoInvalida("ID de produto inválido");
  return parsed.data;
}

// Achata produto_aparicoes (1:N) num array `canais` ordenado pela primeira
// vez que cada canal viu a promo. Mantém canal_origem para compat.
function projetarCanais(produto) {
  if (!produto) return produto;
  const aparicoes = produto.produto_aparicoes || [];
  const ordenadas = [...aparicoes].sort((a, b) => {
    const ta = a.visto_em ? Date.parse(a.visto_em) : 0;
    const tb = b.visto_em ? Date.parse(b.visto_em) : 0;
    return ta - tb;
  });
  const vistos = new Set();
  const canais = [];
  for (const ap of ordenadas) {
    if (ap.canal_origem && !vistos.has(ap.canal_origem)) {
      vistos.add(ap.canal_origem);
      canais.push(ap.canal_origem);
    }
  }
  if (canais.length === 0 && produto.canal_origem) {
    canais.push(produto.canal_origem);
  }
  // Defesa adicional: mesmo retorno de RPC nunca publica payload/identidade privada.
  const publico = Object.fromEntries(CAMPOS_PUBLICOS
    .filter((campo) => Object.hasOwn(produto, campo)).map((campo) => [campo, produto[campo]]));
  return { ...publico, canais };
}

export function criarProdutoService(model = ProdutoModel) {
  return {
    async listar(filtros) {
      const parsed = listarSchema.safeParse(filtros ?? {});
      if (!parsed.success) {
        throw RequisicaoInvalida(parsed.error.issues[0].message);
      }
      const lista = await model.listar(parsed.data);
      return (lista || []).map(projetarCanais);
    },

    async detalhar(id) {
      const produto = await model.buscarPorId(validarId(id));
      if (!produto) throw NaoEncontrado("Produto não encontrado");
      return projetarCanais(produto);
    },

    async estatisticas() {
      const porCategoria = await model.contarPorCategoria();
      const total = Object.values(porCategoria).reduce((a, b) => a + b, 0);
      return { total, porCategoria };
    },

    async remover(id) {
      // A decisão de resolver alias/terminalizar é uma única transação, sem TOCTOU.
      const removido = await model.remover(validarId(id));
      if (!removido) throw NaoEncontrado("Produto não encontrado");
    },
  };
}

export const ProdutoService = criarProdutoService();
