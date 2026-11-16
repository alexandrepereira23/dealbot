import { MidiaService } from "../services/midia.service.js";

function cabecalhos(res, tamanho) {
  res.set({
    "Content-Type": "image/webp",
    "Content-Length": String(tamanho),
    "Cache-Control": "public, max-age=3600",
    "X-Content-Type-Options": "nosniff",
  });
}

async function responder(servico, req, res, next, corpo) {
  try {
    const midia = await servico.buscar(req.params.chave);
    if (!midia) {
      res.set("Cache-Control", "no-store");
      return res.status(404).end();
    }
    cabecalhos(res, midia.tamanho);
    return corpo ? res.status(200).send(midia.dados) : res.status(200).end();
  } catch (erro) {
    return next(erro);
  }
}

export function criarMidiaController(servico = MidiaService) {
  return {
    exibir(req, res, next) {
      return responder(servico, req, res, next, true);
    },
    cabecalhos(req, res, next) {
      return responder(servico, req, res, next, false);
    },
  };
}

export const MidiaController = criarMidiaController();
