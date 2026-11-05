import { FiltroService } from "../services/filtro.service.js";

export function criarFiltroController(servico = FiltroService) {
  return {
    async listar(req, res, next) {
      try {
        res.json(await servico.listar());
      } catch (e) {
        next(e);
      }
    },

    async criar(req, res, next) {
      try {
        const filtro = await servico.criar(req.body);
        res.status(201).json(filtro);
      } catch (e) {
        next(e);
      }
    },

    async atualizar(req, res, next) {
      try {
        const filtro = await servico.atualizar(req.params.id, req.body);
        res.json(filtro);
      } catch (e) {
        next(e);
      }
    },

    async remover(req, res, next) {
      try {
        await servico.remover(req.params.id);
        res.status(204).end();
      } catch (e) {
        next(e);
      }
    },
  };
}

export const FiltroController = criarFiltroController();
