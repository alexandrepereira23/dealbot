import dotenv from "dotenv";
dotenv.config();

function obrigatorio(chave) {
  const valor = process.env[chave];
  if (!valor) throw new Error(`Variável de ambiente ausente: ${chave}`);
  return valor;
}

const nodeEnv = process.env.NODE_ENV || "development";

function inteiroPositivo(chave, padrao, maximo, minimo = 1) {
  const valor = Number(process.env[chave] ?? padrao);
  if (!Number.isInteger(valor) || valor < minimo || valor > maximo) {
    throw new Error(`Variável de ambiente inválida: ${chave}`);
  }
  return valor;
}

function booleano(chave, padrao) {
  const valor = process.env[chave] ?? String(padrao);
  if (valor !== "true" && valor !== "false") {
    throw new Error(`Variável de ambiente inválida: ${chave}`);
  }
  return valor === "true";
}

function diretorioAbsolutoOpcional(chave) {
  const valor = process.env[chave];
  if (!valor) return null;
  // Não resolver/normalizar aqui: o model verifica lstat e nunca aceita raiz-link.
  if (!/^(?:[A-Za-z]:[\\/]|\/)/.test(valor)) {
    throw new Error(`Variável de ambiente inválida: ${chave}`);
  }
  return valor;
}

// Em produção, CORS_ORIGIN é obrigatório — nunca abrir para "*" sem querer.
// Em dev, default para o Next em localhost:3000.
function resolverCorsOrigin() {
  const valor = process.env.CORS_ORIGIN;
  if (!valor) {
    if (nodeEnv === "production") {
      throw new Error(
        "CORS_ORIGIN é obrigatório em produção (lista separada por vírgula).",
      );
    }
    return "http://localhost:3000";
  }
  return valor;
}

export const env = {
  nodeEnv,
  port: process.env.PORT || 3333,
  host: process.env.HOST || "0.0.0.0",
  supabaseUrl: obrigatorio("SUPABASE_URL"),
  supabaseServiceKey: obrigatorio("SUPABASE_SERVICE_KEY"),
  supabaseAnonKey: obrigatorio("SUPABASE_ANON_KEY"),
  corsOrigin: resolverCorsOrigin(),
  retencaoHoras: inteiroPositivo("RETENCAO_HORAS", 48, 8760),
  retencaoDias: inteiroPositivo("RETENCAO_DIAS", 7, 3650, 7),
  limpezaIntervaloMin: inteiroPositivo("LIMPEZA_INTERVALO_MIN", 60, 10080),
  limpezaAtiva: booleano("LIMPEZA_ATIVA", true),
  limpezaLote: inteiroPositivo("LIMPEZA_LOTE", 100, 500),
  limpezaMaxLotes: inteiroPositivo("LIMPEZA_MAX_LOTES", 10, 100),
  midiaLocalDir: diretorioAbsolutoOpcional("MIDIA_LOCAL_DIR"),
  midiaSaidaMaxBytes: inteiroPositivo("MIDIA_SAIDA_MAX_BYTES", 358400, 1048576),
};
