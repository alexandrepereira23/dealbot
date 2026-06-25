export class HttpError extends Error {
  constructor(status, mensagem) {
    super(mensagem);
    this.status = status;
    this.name = "HttpError";
  }
}

export const NaoEncontrado = (msg = "Recurso não encontrado") =>
  new HttpError(404, msg);
export const RequisicaoInvalida = (msg = "Requisição inválida") =>
  new HttpError(400, msg);
export const NaoAutorizado = (msg = "Não autorizado") =>
  new HttpError(401, msg);
