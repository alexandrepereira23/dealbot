const TABELA = "filtros";
const COLUNAS = "id,nome,palavras_chave,palavras_bloqueio,categoria,preco_max,ativo,criado_em,tipo_regra,modo_palavras";

// Injeção mantém testes offline sem carregar configuração/credenciais de produção.
export function criarFiltroModel(obterCliente = async () =>
  (await import("../config/supabase.js")).supabaseAdmin) {
  return {
    async listar() {
      const supabaseAdmin = await obterCliente();
      const { data, error } = await supabaseAdmin
        .from(TABELA)
        .select(COLUNAS)
        .order("criado_em", { ascending: false });
      if (error) throw error;
      return data;
    },

    async buscarPorId(id) {
      const supabaseAdmin = await obterCliente();
      const { data, error } = await supabaseAdmin.from(TABELA)
        .select(COLUNAS).eq("id", id).maybeSingle();
      if (error) throw error;
      return data;
    },

    async criar(filtro) {
      const supabaseAdmin = await obterCliente();
      const { data, error } = await supabaseAdmin
        .from(TABELA)
        .insert(filtro)
        .select(COLUNAS)
        .single();
      if (error) throw error;
      return data;
    },

    async atualizar(id, campos) {
      const supabaseAdmin = await obterCliente();
      const { data, error } = await supabaseAdmin
        .from(TABELA)
        .update(campos)
        .eq("id", id)
        .select(COLUNAS)
        .maybeSingle();
      if (error) throw error;
      return data;
    },

    async remover(id) {
      const supabaseAdmin = await obterCliente();
      const { error } = await supabaseAdmin.from(TABELA).delete().eq("id", id);
      if (error) throw error;
    },
  };
}

export const FiltroModel = criarFiltroModel();
