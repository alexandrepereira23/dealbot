import { CanalService } from "../services/canal.service.js";

export const CanalController = {
  async listar(req, res, next) {
    try {
      res.json(await CanalService.listar());
    } catch (e) {
      next(e);
    }
  },

  async criar(req, res, next) {
    try {
      const canal = await CanalService.criar(req.body);
      res.status(201).json(canal);
    } catch (e) {
      next(e);
    }
  },

  async atualizar(req, res, next) {
    try {
      const canal = await CanalService.atualizar(req.params.id, req.body);
      res.json(canal);
    } catch (e) {
      next(e);
    }
  },

  async remover(req, res, next) {
    try {
      await CanalService.remover(req.params.id);
      res.status(204).end();
    } catch (e) {
      next(e);
    }
  },
};
