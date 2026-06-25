import { supabaseAdmin } from "../config/supabase.js";

const TABELA = "canais";

export const CanalModel = {
  async listar() {
    const { data, error } = await supabaseAdmin
      .from(TABELA)
      .select("*")
      .order("criado_em", { ascending: false });
    if (error) throw error;
    return data;
  },

  async criar(canal) {
    const { data, error } = await supabaseAdmin
      .from(TABELA)
      .insert(canal)
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
