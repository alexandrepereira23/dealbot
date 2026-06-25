import { Router } from "express";
import { autenticar } from "../middlewares/auth.middleware.js";
import produtoRoutes from "./produto.routes.js";
import filtroRoutes from "./filtro.routes.js";
import canalRoutes from "./canal.routes.js";

const router = Router();

// Healthcheck público
router.get("/health", (req, res) => res.json({ status: "ok" }));

// Tudo abaixo exige usuário autenticado
router.use(autenticar);
router.use("/produtos", produtoRoutes);
router.use("/filtros", filtroRoutes);
router.use("/canais", canalRoutes);

export default router;
