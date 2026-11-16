import { HttpError } from "../utils/errors.js";

// Handler central: qualquer erro passado via next(e) cai aqui.
// eslint-disable-next-line no-unused-vars
export function errorHandler(err, req, res, next) {
  // Falhas de leitura de mídia/configuração não podem tornar erro transitório um
  // cache negativo público; dados em /api já recebem a mesma política antes da
  // autenticação/rate limit.
  // Alguns contratos unitários usam uma resposta mínima sem set(); em Express a
  // política continua aplicada antes de serializar qualquer erro.
  if (typeof res.set === "function") res.set("Cache-Control", "no-store");
  if (err instanceof HttpError) {
    return res.status(err.status).json({ erro: err.message });
  }
  console.error("[erro inesperado]", err);
  res.status(500).json({ erro: "Erro interno do servidor" });
}

export function notFound(req, res) {
  res.set("Cache-Control", "no-store").status(404).json({ erro: "Rota não encontrada" });
}
