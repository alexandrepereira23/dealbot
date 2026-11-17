import fs from "node:fs/promises";
import { constants } from "node:fs";
import { env } from "./config/env.js";
import { supabaseAdmin, supabaseAuth } from "./config/supabase.js";
import { verificarLeituras } from "./models/preflight.model.js";
import { criarMidiaLocalModel } from "./models/midia-local.model.js";

// CLI operacional explícita; não é healthcheck nem inicia servidor/limpeza.
const prazo = setTimeout(() => {
  console.error("preflight: prazo excedido; manter limpeza suspensa");
  process.exit(1);
}, 30_000);
try {
  if (env.limpezaAtiva) throw new Error("preflight_exige_limpeza_suspensa");
  await verificarLeituras(supabaseAdmin);
  console.log("preflight: leituras de schema acessíveis (RPCs/grants exigem inventário SQL separado)");
  if (!env.midiaLocalDir) throw new Error("preflight_midia_ausente");
  const info = await fs.lstat(env.midiaLocalDir);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("preflight_midia_insegura");
  await fs.access(env.midiaLocalDir, constants.R_OK | constants.W_OK | constants.X_OK);
  // Chave inexistente é leitura sem efeitos; exercita abertura ancorada /proc/self/fd.
  await criarMidiaLocalModel().ler("0".repeat(32) + ".webp");
  console.log("preflight: volume acessível por usuário efetivo; publicação/remoção exigem ensaio");
  const token = process.env.DEALBOT_PREFLIGHT_TOKEN;
  if (token) {
    const { data, error } = await supabaseAuth.auth.getUser(token);
    if (error || !data.user) throw new Error("preflight_auth_falhou");
    console.log("preflight: token validado pelo Auth");
  } else {
    console.log("preflight: autenticação NÃO verificada (token não fornecido)");
    process.exitCode = 2;
  }
} catch {
  console.error("preflight: falhou; conferir configuração, schema, permissões e Auth sem habilitar limpeza");
  process.exitCode = 1;
} finally {
  await Promise.allSettled([supabaseAdmin.removeAllChannels(), supabaseAuth.removeAllChannels()]);
  clearTimeout(prazo);
}
