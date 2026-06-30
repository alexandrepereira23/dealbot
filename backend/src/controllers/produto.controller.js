import { ProdutoService } from "../services/produto.service.js";

export const ProdutoController = {
  async listar(req, res, next) {
    try {
      const { categoria, q, limite, offset } = req.query;
      const produtos = await ProdutoService.listar({
        categoria,
        q,
        limite: limite ? Number(limite) : undefined,
        offset: offset ? Number(offset) : undefined,
      });
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
