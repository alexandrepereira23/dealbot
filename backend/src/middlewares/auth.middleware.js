import { supabaseAuth } from "../config/supabase.js";
import { NaoAutorizado } from "../utils/errors.js";

// Lê o header Authorization: Bearer <token>, valida no Supabase
// e anexa req.user. Bloqueia se o token for inválido ou ausente.
export async function autenticar(req, res, next) {
  try {
    const header = req.headers.authorization || "";
    const token = header.startsWith("Bearer ") ? header.slice(7) : null;
    if (!token) throw NaoAutorizado("Token ausente");

    const { data, error } = await supabaseAuth.auth.getUser(token);
    if (error || !data?.user) throw NaoAutorizado("Token inválido");

    req.user = data.user;
    next();
  } catch (e) {
    next(e);
  }
}
