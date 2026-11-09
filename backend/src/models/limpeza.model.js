const BUCKET = "produtos";

function chaveStorage(fotoUrl, supabaseUrl) {
  const base = new URL(supabaseUrl);
  const url = new URL(fotoUrl);
  const prefixo = `${base.pathname.replace(/\/$/, "")}/storage/v1/object/public/${BUCKET}/`;
  if (url.origin !== base.origin || url.username || url.password ||
      url.search || url.hash || !url.pathname.startsWith(prefixo)) {
    throw new Error("URL de mídia fora do bucket configurado");
  }
  const chave = decodeURIComponent(url.pathname.slice(prefixo.length));
  if (!chave || /[\\\x00-\x1f\x7f]/.test(chave) ||
      chave.split("/").some((parte) => !parte || parte === "." || parte === "..")) {
    throw new Error("Chave de mídia inválida");
  }
  // O lock remoto usa URL exata: não aceitar aliases de encoding/dot-segments
  // que apontem à mesma chave de outra URL ainda referenciada.
  if (fotoUrl !== `${base.origin}${prefixo}${encodeURI(chave)}`) {
    throw new Error("URL de mídia não canônica");
  }
  return chave;
}

export function criarLimpezaModel(obterCliente = async () =>
  (await import("../config/supabase.js")).supabaseAdmin,
  obterSupabaseUrl = async () => (await import("../config/env.js")).env.supabaseUrl) {
  return {
    async prepararLote({ retencaoHoras, retencaoDias, lote }) {
      const cliente = await obterCliente();
      const { data, error } = await cliente.rpc("oferta_limpar", {
        p_retencao_horas: retencaoHoras, p_retencao_dias: retencaoDias, p_lote: lote,
      });
      if (error) throw error;
      if (!Array.isArray(data) || data.some((item) =>
        !["expirado", "purgado", "midia_pendente"].includes(item.status) ||
        (item.status === "midia_pendente" ? typeof item.url !== "string" : item.url !== null))) {
        throw new Error("Contrato de limpeza incompatível");
      }
      const urls = data.filter((item) => item.status === "midia_pendente").map((item) => item.url);
      const processadas = data.length - urls.length;
      return { urls, processadas, continuar: urls.length >= lote ||
        ["expirado", "purgado"].some((status) => data.filter((item) => item.status === status).length >= lote) };
    },

    async reservarRemocao(url) {
      const cliente = await obterCliente();
      const { data, error } = await cliente.rpc("midia_reservar_remocao", { p_url: url });
      if (error) throw error;
      if (!Array.isArray(data) || data.length !== 1 || typeof data[0].permitido !== "boolean") {
        throw new Error("Contrato de reserva de mídia incompatível");
      }
      return data[0].permitido;
    },

    async apagarFoto(url) {
      // Só chaves conhecidas deste projeto/bucket. Nunca lista nem varre Storage.
      const chave = chaveStorage(url, await obterSupabaseUrl());
      const cliente = await obterCliente();
      const { error } = await cliente.storage.from(BUCKET).remove([chave]);
      if (error) throw error;
    },

    async confirmarRemocao(url) {
      const cliente = await obterCliente();
      const { data, error } = await cliente.rpc("midia_confirmar_remocao", { p_url: url });
      if (error) throw error;
      if (!Array.isArray(data) || data.length !== 1 || data[0].status !== "confirmado") {
        throw new Error("Confirmação de mídia não persistida");
      }
    },
  };
}

export const LimpezaModel = criarLimpezaModel();
