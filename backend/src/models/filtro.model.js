import { supabaseAdmin } from "../config/supabase.js";

const TABELA = "filtros";

export const FiltroModel = {
  async listar() {
    const { data, error } = await supabaseAdmin
      .from(TABELA)
      .select("*")
      .order("criado_em", { ascending: false });
    if (error) throw error;
    return data;
  },

  async criar(filtro) {
    const { data, error } = await supabaseAdmin
      .from(TABELA)
      .insert(filtro)
      .select()
      .single();
    if (error) throw error;
    return data;
  },

  async atualizar(id, campos) {
    const { data, error } = await supabaseAdmin
      .from(TABELA)
      .update(campos)
      .eq("id", id)
      .select()
      .single();
    if (error) throw error;
    return data;
  },

  async remover(id) {
    const { error } = await supabaseAdmin.from(TABELA).delete().eq("id", id);
    if (error) throw error;
  },
};
