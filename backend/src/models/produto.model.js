import { supabaseAdmin } from "../config/supabase.js";

const TABELA = "produtos";

// Escapa wildcards do LIKE/ILIKE para o termo do usuário ser tratado como literal.
// Vírgula é escapada porque o .or() do supabase-js usa vírgula como separador.
function escaparTermoLike(termo) {
  return termo
    .replace(/\\/g, "\\\\")
    .replace(/%/g, "\\%")
    .replace(/_/g, "\\_")
    .replace(/,/g, "\\,");
}

export const ProdutoModel = {
  async listar({ categoria, q, limite = 60, offset = 0 } = {}) {
    let query = supabaseAdmin
      .from(TABELA)
      .select("*")
      .order("data_oferta", { ascending: false, nullsFirst: false })
      .order("criado_em", { ascending: false })
      .range(offset, offset + limite - 1);

    if (categoria && categoria !== "todos") {
      query = query.eq("categoria", categoria);
    }

    const termo = typeof q === "string" ? q.trim() : "";
    if (termo.length >= 2) {
      const padrao = `%${escaparTermoLike(termo)}%`;
      query = query.or(`titulo.ilike.${padrao},raw_text.ilike.${padrao}`);
    }

    const { data, error } = await query;
    if (error) throw error;
    return data;
  },

  async buscarPorId(id) {
    const { data, error } = await supabaseAdmin
      .from(TABELA)
      .select("*")
      .eq("id", id)
      .single();
    if (error) throw error;
    return data;
  },

  async contarPorCategoria() {
    const { data, error } = await supabaseAdmin.from(TABELA).select("categoria");
    if (error) throw error;
    const contagem = {};
    for (const row of data) {
      contagem[row.categoria] = (contagem[row.categoria] || 0) + 1;
    }
    return contagem;
  },

  async remover(id) {
    const { error } = await supabaseAdmin.from(TABELA).delete().eq("id", id);
    if (error) throw error;
  },
};
