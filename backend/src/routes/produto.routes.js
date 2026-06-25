import { Router } from "express";
import { ProdutoController } from "../controllers/produto.controller.js";

const router = Router();

router.get("/", ProdutoController.listar);
router.get("/estatisticas", ProdutoController.estatisticas);
router.get("/:id", ProdutoController.detalhar);
router.delete("/:id", ProdutoController.remover);

export default router;
