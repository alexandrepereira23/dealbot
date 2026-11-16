import { Router } from "express";
import { MidiaController } from "../controllers/midia.controller.js";

export function criarMidiaRoutes(controller = MidiaController) {
  const router = Router();

  // Esta rota é propositalmente pública como o bucket legado: só aceita uma
  // chave opaca/final e nunca atravessa para dados ou endpoints autenticados.
  router.use((req, res, next) => {
    if (req.originalUrl.includes("?")) {
      return res.set("Cache-Control", "no-store").status(404).end();
    }
    return next();
  });
  router.head("/:chave([a-f0-9]{32}\\.webp)", controller.cabecalhos);
  router.get("/:chave([a-f0-9]{32}\\.webp)", controller.exibir);
  router.all("*", (req, res) => res.set("Cache-Control", "no-store").status(404).end());
  return router;
}

export default criarMidiaRoutes();
