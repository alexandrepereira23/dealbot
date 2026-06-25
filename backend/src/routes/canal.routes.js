import { Router } from "express";
import { CanalController } from "../controllers/canal.controller.js";

const router = Router();

router.get("/", CanalController.listar);
router.post("/", CanalController.criar);
router.put("/:id", CanalController.atualizar);
router.delete("/:id", CanalController.remover);

export default router;
