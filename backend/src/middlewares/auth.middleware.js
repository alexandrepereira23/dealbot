import {
  AuthInvalidJwtError, isAuthApiError, isAuthRetryableFetchError, isAuthSessionMissingError,
} from "@supabase/supabase-js";
import { supabaseAuth } from "../config/supabase.js";
import { HttpError, NaoAutorizado } from "../utils/errors.js";

const CODIGOS_TRANSITORIOS = new Set(["request_timeout", "over_request_rate_limit",
  "hook_timeout", "hook_timeout_after_retry"]);
const CODIGOS_CREDENCIAL_INVALIDA = new Set(["bad_jwt", "session_not_found",
  "session_expired", "user_not_found", "user_banned"]);

function erroValidacao(erro) {
  // Contrato do auth-js instalado: fetch/rede e gateways usam a classe retryable;
  // outros erros HTTP preservam status/code. Nunca inferir pela mensagem.
  if (isAuthRetryableFetchError(erro) || (isAuthApiError(erro) && (
    erro.status === 408 || erro.status === 429 || (erro.status >= 500 && erro.status <= 599)
    || CODIGOS_TRANSITORIOS.has(erro.code)
  ))) {
    return new HttpError(503, "Serviço de autenticação temporariamente indisponível");
  }
  if (isAuthSessionMissingError(erro) || erro instanceof AuthInvalidJwtError
    || (isAuthApiError(erro) && erro.status >= 400 && erro.status < 500
      && CODIGOS_CREDENCIAL_INVALIDA.has(erro.code))) {
    return NaoAutorizado("Token inválido");
  }
  // Falha técnica desconhecida não comprova invalidez da credencial. Sanear aqui
  // também impede que o handler central registre payload/token do provedor.
  return new HttpError(500, "Erro interno do servidor");
}

// Lê o header Authorization: Bearer <token>, valida no Supabase
// e só anexa req.user depois de validação bem-sucedida. Toda falha nega acesso.
export async function autenticar(req, res, next) {
  const header = req.headers.authorization || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) return next(NaoAutorizado("Token ausente"));

  let resultado;
  try {
    resultado = await supabaseAuth.auth.getUser(token);
  } catch (e) {
    return next(erroValidacao(e));
  }
  if (resultado?.error) return next(erroValidacao(resultado.error));
  const usuario = resultado?.data?.user;
  // Resposta incompleta do provedor não é prova de token inválido nem de acesso.
  if (typeof usuario?.id !== "string" || !usuario.id) return next(erroValidacao(null));

  req.user = usuario;
  next();
}
