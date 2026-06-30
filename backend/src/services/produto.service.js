import { z } from "zod";
import { ProdutoModel } from "../models/produto.model.js";
import { NaoEncontrado, RequisicaoInvalida } from "../utils/errors.js";

const listarSchema = z.object({
  categoria: z.string().max(50).optional(),
  q: z.string().max(200).optional(),
  limite: z.coerce.number().int().min(1).max(100).default(60),
  offset: z.coerce.number().int().min(0).default(0),
});

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
  const { produto_aparicoes, ...resto } = produto;
  return { ...resto, canais };
}

export const ProdutoService = {
  async listar(filtros) {
    const parsed = listarSchema.safeParse(filtros ?? {});
    if (!parsed.success) {
      throw RequisicaoInvalida(parsed.error.issues[0].message);
    }
    const lista = await ProdutoModel.listar(parsed.data);
    return (lista || []).map(projetarCanais);
  },

  async detalhar(id) {
    const produto = await ProdutoModel.buscarPorId(id).catch(() => null);
    if (!produto) throw NaoEncontrado("Produto não encontrado");
    return projetarCanais(produto);
  },

  async estatisticas() {
    const porCategoria = await ProdutoModel.contarPorCategoria();
    const total = Object.values(porCategoria).reduce((a, b) => a + b, 0);
    return { total, porCategoria };
  },

  async remover(id) {
    await this.detalhar(id);
    await ProdutoModel.remover(id);
  },
};
