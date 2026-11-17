// Leituras limitadas: não chama RPC de prontidão legada, reserva ou limpeza.
const PROJECOES = {
  produtos: "id,canal_id,identidade_versao,identidade_dados,canonico_id,estado_oferta,expira_em,preco_anterior_atualizacao,preco_observado_em",
  produto_aparicoes: "id,canal_id,telegram_msg_id,produto_id",
  filtros: "id,tipo_regra,modo_palavras,palavras_chave,palavras_bloqueio,categoria,preco_max,ativo",
  canais: "id,username,ativo",
  oferta_eventos: "canal_id,msg_id,pin,confirmado_em,resultado_inicial",
  oferta_midias: "url,estado,confirmado_em",
  oferta_controle: "id,legado_pronto",
};

export async function verificarLeituras(cliente) {
  for (const [tabela, colunas] of Object.entries(PROJECOES)) {
    const { error } = await cliente.from(tabela).select(colunas).limit(0)
      .abortSignal(AbortSignal.timeout(15_000));
    if (error) throw new Error(`preflight_schema_${tabela}`);
  }
}
