import express from "express";
import cors from "cors";
import { env } from "./config/env.js";
import routes from "./routes/index.js";
import { errorHandler, notFound } from "./middlewares/error.middleware.js";

export function criarApp() {
  const app = express();

  app.use(cors({ origin: env.corsOrigin }));
  app.use(express.json());

  app.use("/api", routes);

  app.use(notFound);
  app.use(errorHandler);

  return app;
}
