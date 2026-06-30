import { ProdutoService } from "../services/produto.service.js";

export const ProdutoController = {
  async listar(req, res, next) {
    try {
      // Zod coage e valida no service — controller só repassa o objeto.
      const produtos = await ProdutoService.listar(req.query);
      res.json(produtos);
    } catch (e) {
      next(e);
    }
  },

  async detalhar(req, res, next) {
    try {
      const produto = await ProdutoService.detalhar(req.params.id);
      res.json(produto);
    } catch (e) {
      next(e);
    }
  },

  async estatisticas(req, res, next) {
    try {
      res.json(await ProdutoService.estatisticas());
    } catch (e) {
      next(e);
    }
  },

  async remover(req, res, next) {
    try {
      await ProdutoService.remover(req.params.id);
      res.status(204).end();
    } catch (e) {
      next(e);
    }
  },
};
