import { FiltroService } from "../services/filtro.service.js";

export const FiltroController = {
  async listar(req, res, next) {
    try {
      res.json(await FiltroService.listar());
    } catch (e) {
      next(e);
    }
  },

  async criar(req, res, next) {
    try {
      const filtro = await FiltroService.criar(req.body);
      res.status(201).json(filtro);
    } catch (e) {
      next(e);
    }
  },

  async atualizar(req, res, next) {
    try {
      const filtro = await FiltroService.atualizar(req.params.id, req.body);
      res.json(filtro);
    } catch (e) {
      next(e);
    }
  },

  async remover(req, res, next) {
    try {
      await FiltroService.remover(req.params.id);
      res.status(204).end();
    } catch (e) {
      next(e);
    }
  },
};
