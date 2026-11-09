const TABELA = "produtos";
const COLUNAS_PUBLICAS = "id,titulo,preco,preco_original,cupom,link,foto_url,categoria,canal_origem,criado_em,data_oferta,preco_anterior_atualizacao,preco_observado_em,atualizado_em,ultima_aparicao_em,expira_em";
const COLUNAS = `${COLUNAS_PUBLICAS},produto_aparicoes(canal_origem,visto_em)`;

// A mesma janela/instante governa lista, detalhe e todas as páginas da contagem.
function elegiveis(query, retencaoHoras, instante) {
  const agora = new Date(instante).toISOString();
  const corteLegado = new Date(instante - retencaoHoras * 3600_000).toISOString();
  return query.eq("estado_oferta", "ativa").is("canonico_id", null)
    .or(`and(identidade_versao.is.null,criado_em.gt.${corteLegado}),and(identidade_versao.not.is.null,expira_em.gt.${agora})`);
}

// Escapa wildcards do LIKE/ILIKE para o termo do usuário ser tratado como literal.
// Vírgula é escapada porque o .or() do supabase-js usa vírgula como separador.
function escaparTermoLike(termo) {
  return termo
    .replace(/\\/g, "\\\\")
    .replace(/%/g, "\\%")
    .replace(/_/g, "\\_")
    .replace(/,/g, "\\,");
}

// Não importa env/Auth nos testes; apenas models conhecem o cliente de banco.
export function criarProdutoModel(obterCliente = async () =>
  (await import("../config/supabase.js")).supabaseAdmin, {
  obterRetencaoHoras = async () => (await import("../config/env.js")).env.retencaoHoras,
  agora = Date.now,
} = {}) {
  return {
    async listar({ categoria, q, limite = 60, offset = 0 } = {}) {
      const supabaseAdmin = await obterCliente();
      let query = elegiveis(supabaseAdmin.from(TABELA).select(COLUNAS),
        await obterRetencaoHoras(), agora())
        .order("data_oferta", { ascending: false, nullsFirst: false })
        .order("criado_em", { ascending: false })
        .order("id", { ascending: false })
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
      const supabaseAdmin = await obterCliente();
      const query = supabaseAdmin.rpc("oferta_buscar", { p_id: id }).select(COLUNAS);
      const { data, error } = await elegiveis(query,
        await obterRetencaoHoras(), agora()).maybeSingle();
      if (error) throw error;
      return data;
    },

    async contarPorCategoria() {
      const supabaseAdmin = await obterCliente();
      const retencaoHoras = await obterRetencaoHoras();
      const instante = agora();
      const contagem = {};
      // Não truncar estatísticas no limite padrão de linhas do PostgREST.
      const lote = 1000;
      for (let offset = 0; ; offset += lote) {
        const { data, error } = await elegiveis(supabaseAdmin.from(TABELA)
          .select("categoria"), retencaoHoras, instante)
          .order("id", { ascending: true }).range(offset, offset + lote - 1);
        if (error) throw error;
        for (const row of data || []) {
          contagem[row.categoria] = (contagem[row.categoria] || 0) + 1;
        }
        if (!data || data.length < lote) break;
      }
      return contagem;
    },

    async remover(id) {
      const supabaseAdmin = await obterCliente();
      const { data, error } = await supabaseAdmin.rpc("oferta_remover", { p_id: id });
      if (error) throw error;
      if (!Array.isArray(data) || data.length !== 1 ||
          !["removido", "ausente"].includes(data[0].status)) {
        throw new Error("Contrato de remoção de oferta incompatível");
      }
      return data[0].status === "removido";
    },
  };
}

export const ProdutoModel = criarProdutoModel();
