import { LimpezaModel } from "../models/limpeza.model.js";

function validarConfiguracao(config) {
  for (const [campo, maximo] of [["retencaoHoras", 8760], ["retencaoDias", 3650],
    ["limpezaLote", 500], ["limpezaMaxLotes", 100]]) {
    const minimo = campo === "retencaoDias" ? 7 : 1;
    if (!Number.isInteger(config[campo]) || config[campo] < minimo || config[campo] > maximo) {
      throw new Error(`Configuração de limpeza inválida: ${campo}`);
    }
  }
  return config;
}

export function criarExecutarLimpeza(model = LimpezaModel,
  obterConfiguracao = async () => (await import("../config/env.js")).env,
  log = console) {
  let emCurso = null;

  async function ciclo() {
    const inicio = Date.now();
    const resultado = { lotes: 0, fotos: 0, falhas: 0 };
    try {
      const config = validarConfiguracao(await obterConfiguracao());
      const tentadas = new Set();
      for (let n = 0; n < config.limpezaMaxLotes; n++) {
        // Terminalização e intenção de remoção são remotas e duráveis antes do Storage.
        const { urls: candidatas, processadas, continuar } = await model.prepararLote({
          retencaoHoras: config.retencaoHoras, retencaoDias: config.retencaoDias,
          lote: config.limpezaLote,
        });
        resultado.lotes++;
        let novas = 0;
        for (const url of candidatas) {
          if (tentadas.has(url)) continue;
          tentadas.add(url);
          novas++;
          try {
            if (!await model.reservarRemocao(url)) continue;
            await model.apagarFoto(url);
            // Resposta perdida/Storage indisponível deixa a intenção para o próximo ciclo.
            await model.confirmarRemocao(url);
            resultado.fotos++;
          } catch {
            resultado.falhas++;
            log.warn("[limpeza] mídia pendente; remoção será retomada");
          }
        }
        if (!continuar || (novas === 0 && processadas === 0)) break;
      }
    } catch {
      resultado.falhas++;
      // Mensagens do banco/Storage podem conter URL/token: não registrá-las.
      log.error("[limpeza] falha; pendências remotas preservadas");
    }
    log.log(`[limpeza] lotes=${resultado.lotes} fotos=${resultado.fotos} falhas=${resultado.falhas} duracao=${Date.now() - inicio}ms`);
    return resultado;
  }

  // Boot e intervalos compartilham a mesma promessa, sem enfileirar ciclos extras.
  return function executar() {
    if (!emCurso) emCurso = ciclo().finally(() => { emCurso = null; });
    return emCurso;
  };
}

export const executarLimpeza = criarExecutarLimpeza();
