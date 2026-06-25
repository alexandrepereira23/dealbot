import dotenv from "dotenv";
dotenv.config();

function obrigatorio(chave) {
  const valor = process.env[chave];
  if (!valor) throw new Error(`Variável de ambiente ausente: ${chave}`);
  return valor;
}

export const env = {
  port: process.env.PORT || 3333,
  supabaseUrl: obrigatorio("SUPABASE_URL"),
  supabaseServiceKey: obrigatorio("SUPABASE_SERVICE_KEY"),
  supabaseAnonKey: obrigatorio("SUPABASE_ANON_KEY"),
  corsOrigin: process.env.CORS_ORIGIN || "*",
};
