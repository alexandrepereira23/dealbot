import { ProdutoModel } from "../models/produto.model.js";
import { NaoEncontrado } from "../utils/errors.js";

export const ProdutoService = {
  async listar(filtros) {
    return ProdutoModel.listar(filtros);
  },

  async detalhar(id) {
    const produto = await ProdutoModel.buscarPorId(id).catch(() => null);
    if (!produto) throw NaoEncontrado("Produto não encontrado");
    return produto;
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
