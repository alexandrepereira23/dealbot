import { supabaseAdmin } from "../config/supabase.js";

const TABELA = "produtos";

export const ProdutoModel = {
  async listar({ categoria, limite = 60, offset = 0 } = {}) {
    let query = supabaseAdmin
      .from(TABELA)
      .select("*")
      .order("criado_em", { ascending: false })
      .range(offset, offset + limite - 1);

    if (categoria && categoria !== "todos") {
      query = query.eq("categoria", categoria);
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
