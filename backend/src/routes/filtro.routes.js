import { Router } from "express";
import { FiltroController } from "../controllers/filtro.controller.js";

export function criarFiltroRouter(controller = FiltroController) {
  const router = Router();

  router.get("/", controller.listar);
  router.post("/", controller.criar);
  router.put("/:id", controller.atualizar);
  router.delete("/:id", controller.remover);
  return router;
}

export default criarFiltroRouter();
