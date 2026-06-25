import { Router } from "express";
import { FiltroController } from "../controllers/filtro.controller.js";

const router = Router();

router.get("/", FiltroController.listar);
router.post("/", FiltroController.criar);
router.put("/:id", FiltroController.atualizar);
router.delete("/:id", FiltroController.remover);

export default router;
