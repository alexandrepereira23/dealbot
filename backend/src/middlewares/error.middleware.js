import { HttpError } from "../utils/errors.js";

// Handler central: qualquer erro passado via next(e) cai aqui.
// eslint-disable-next-line no-unused-vars
export function errorHandler(err, req, res, next) {
  if (err instanceof HttpError) {
    return res.status(err.status).json({ erro: err.message });
  }
  console.error("[erro inesperado]", err);
  res.status(500).json({ erro: "Erro interno do servidor" });
}

export function notFound(req, res) {
  res.status(404).json({ erro: "Rota não encontrada" });
}
