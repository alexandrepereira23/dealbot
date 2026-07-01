import { supabaseAdmin } from "../config/supabase.js";
import { env } from "../config/env.js";

const BUCKET = "produtos";
const LOTE = 500;

function extrairNomeArquivo(fotoUrl) {
  if (!fotoUrl || typeof fotoUrl !== "string") return null;
  try {
    const nome = new URL(fotoUrl).pathname.split("/").pop();
    return nome && nome.endsWith(".jpg") ? nome : null;
  } catch {
    return null;
  }
}

async function apagarLote(cutoffIso) {
  const { data, error } = await supabaseAdmin
    .from("produtos")
    .select("id, foto_url")
    .lt("criado_em", cutoffIso)
    .limit(LOTE);

  if (error) throw error;
  if (!data || data.length === 0) return { linhas: 0, fotos: 0 };

  const ids = data.map((r) => r.id);
  const nomes = data
    .map((r) => extrairNomeArquivo(r.foto_url))
    .filter((n) => n !== null);

  let fotosApagadas = 0;
  if (nomes.length > 0) {
    const { error: errStorage } = await supabaseAdmin.storage
      .from(BUCKET)
      .remove(nomes);
    if (errStorage) {
      console.warn(`[limpeza] falha ao remover fotos: ${errStorage.message}`);
    } else {
      fotosApagadas = nomes.length;
    }
  }

  const { error: errDel } = await supabaseAdmin
    .from("produtos")
    .delete()
    .in("id", ids);
  if (errDel) throw errDel;

  return { linhas: ids.length, fotos: fotosApagadas };
}

export async function executarLimpeza() {
  const inicio = Date.now();
  const cutoff = new Date(
    Date.now() - env.retencaoHoras * 3600_000,
  ).toISOString();

  try {
    let totalLinhas = 0;
    let totalFotos = 0;
    while (true) {
      const { linhas, fotos } = await apagarLote(cutoff);
      totalLinhas += linhas;
      totalFotos += fotos;
      if (linhas < LOTE) break;
    }
    const duracao = Date.now() - inicio;
    console.log(
      `[limpeza] cutoff=${cutoff} linhas=${totalLinhas} fotos=${totalFotos} duracao=${duracao}ms`,
    );
  } catch (e) {
    console.error(`[limpeza] erro: ${e?.message ?? e}`);
  }
}
