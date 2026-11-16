import express from "express";
import cors from "cors";
import helmet from "helmet";
import rateLimit from "express-rate-limit";

import { env } from "./config/env.js";
import routes from "./routes/index.js";
import midiaRoutes from "./routes/midia.routes.js";
import { errorHandler, notFound } from "./middlewares/error.middleware.js";

const origensPermitidas = env.corsOrigin
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

export function criarApp() {
  const app = express();

  // Atrás de proxy reverso (Railway/Nginx) — necessário para rate-limit ler IP real.
  app.set("trust proxy", 1);

  // Cabeçalhos defensivos (X-Frame-Options, HSTS, etc.). CSP fica no frontend.
  app.use(
    helmet({
      contentSecurityPolicy: false,
      crossOriginResourcePolicy: { policy: "cross-origin" },
    }),
  );

  // CORS estrito: só origens listadas em CORS_ORIGIN passam. Requests sem
  // Origin (curl, health checks) são permitidos.
  app.use(
    cors({
      origin(origin, cb) {
        if (!origin || origensPermitidas.includes(origin)) return cb(null, true);
        return cb(new Error("Origem não permitida"));
      },
      credentials: true,
      exposedHeaders: ["Retry-After"],
    }),
  );

  // Limite agressivo no body — endpoints só recebem JSON pequeno.
  app.use(express.json({ limit: "100kb" }));

  // Fotos finais públicas não atravessam o roteador autenticado de dados.
  app.use("/media", midiaRoutes);

  // Snapshots de painel nunca podem ser reaproveitados como atualização atual,
  // inclusive quando o rate limiter encerra a requisição antes do roteador.
  app.use("/api", (req, res, next) => {
    res.set("Cache-Control", "no-store");
    next();
  });

  // Rate limit global. Volume legítimo (~14 req/min/aba) cabe folgado.
  app.use(
    "/api",
    rateLimit({
      windowMs: 60_000,
      max: 120,
      standardHeaders: "draft-7",
      legacyHeaders: false,
      message: { erro: "Muitas requisições. Tente novamente em instantes." },
    }),
  );

  app.use("/api", routes);

  app.use(notFound);
  app.use(errorHandler);

  return app;
}
