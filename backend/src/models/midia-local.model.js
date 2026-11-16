import { constants } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";

export const CHAVE_LOCAL = /^[a-f0-9]{32}\.webp$/;
const LIMITE_PADRAO = 358400;

function webpEstruturalValido(dados) {
  if (!Buffer.isBuffer(dados) || dados.length < 20 || !dados.subarray(0, 4).equals(Buffer.from("RIFF"))
    || !dados.subarray(8, 12).equals(Buffer.from("WEBP")) || dados.readUInt32LE(4) + 8 !== dados.length) {
    return false;
  }
  let posicao = 12;
  let imagem = false;
  while (posicao < dados.length) {
    if (posicao + 8 > dados.length) return false;
    const tipo = dados.subarray(posicao, posicao + 4).toString("ascii");
    const tamanho = dados.readUInt32LE(posicao + 4);
    posicao += 8;
    if (tamanho > dados.length - posicao) return false;
    if (tipo === "VP8 " || tipo === "VP8L") imagem = true;
    if (tipo === "ANIM" || tipo === "ANMF") return false;
    posicao += tamanho + (tamanho % 2);
    if (posicao > dados.length) return false;
  }
  return posicao === dados.length && imagem;
}

export function chaveLocalDaUrl(url) {
  if (typeof url !== "string") return null;
  const resultado = /^\/media\/([a-f0-9]{32}\.webp)$/.exec(url);
  return resultado ? resultado[1] : null;
}

function validarChave(chave) {
  if (typeof chave !== "string" || !CHAVE_LOCAL.test(chave)) {
    throw new Error("Chave local de mídia inválida");
  }
}

async function diretorioSeguro(diretorio) {
  if (typeof diretorio !== "string" || !path.isAbsolute(diretorio)) {
    throw new Error("Diretório local de mídia indisponível");
  }
  // Cada componente até a raiz precisa ser diretório real. Isso impede que uma
  // configuração aparentemente normal atravesse symlink/junction para fora do
  // volume antes que o handle ancorado em Linux entre em ação.
  for (let atual = path.resolve(diretorio); ; atual = path.dirname(atual)) {
    let info;
    try {
      info = await fs.lstat(atual);
    } catch (erro) {
      if (erro?.code === "ENOENT") throw new Error("Diretório local de mídia indisponível");
      throw erro;
    }
    if (!info.isDirectory() || info.isSymbolicLink()) {
      throw new Error("Diretório local de mídia inseguro");
    }
    if (path.dirname(atual) === atual) break;
  }
  return diretorio;
}

function flagsLeitura() {
  // Validar o handle depois de open não basta para FIFO: sem O_NONBLOCK a
  // abertura já bloquearia o worker libuv antes de descobrir que não é regular.
  return constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0);
}

async function abrirRaiz(diretorio) {
  await diretorioSeguro(diretorio);
  const flags = flagsLeitura() | (constants.O_DIRECTORY ?? 0);
  if (process.platform === "linux") {
    // Abrir a raiz inteira após lstat permitiria que um ancestral fosse trocado
    // por link. Cada componente é aberto em relação ao handle anterior, sempre
    // com O_NOFOLLOW; renomear um ancestral não redireciona as próximas operações.
    let raiz = await fs.open(path.parse(diretorio).root, flags);
    try {
      for (const parte of path.resolve(diretorio).split(path.sep).filter(Boolean)) {
        const filho = await fs.open(`/proc/self/fd/${raiz.fd}/${parte}`, flags);
        try {
          if (!(await filho.stat()).isDirectory()) throw new Error("Diretório local de mídia inseguro");
        } catch (erro) {
          await filho.close();
          throw erro;
        }
        const pai = raiz;
        raiz = filho;
        await pai.close();
      }
      return raiz;
    } catch (erro) {
      await raiz.close();
      throw erro;
    }
  }
  const raiz = await fs.open(diretorio, flags);
  try {
    const info = await raiz.stat();
    if (!info.isDirectory()) throw new Error("Diretório local de mídia inseguro");
    return raiz;
  } catch (erro) {
    await raiz.close();
    throw erro;
  }
}

function caminhoAncorado(raiz, diretorio, chave) {
  validarChave(chave);
  // Linux, alvo da VPS, permite abrir o filho pelo handle já verificado da raiz;
  // assim uma troca da raiz por symlink entre lstat/open não sai do volume.
  if (process.platform === "linux") return `/proc/self/fd/${raiz.fd}/${chave}`;
  return path.join(diretorio, chave);
}

async function abrirRegular(raiz, diretorio, chave, limite) {
  const caminho = caminhoAncorado(raiz, diretorio, chave);
  const flags = flagsLeitura();
  let arquivo;
  try {
    arquivo = await fs.open(caminho, flags);
  } catch (erro) {
    if (erro?.code === "ENOENT" || erro?.code === "ELOOP") return null;
    throw erro;
  }
  try {
    const info = await arquivo.stat();
    if (!info.isFile() || info.size <= 0 || info.size > limite) {
      throw new Error("Arquivo local de mídia inseguro");
    }
    const dados = await arquivo.readFile();
    // Arquivo final publicado pelo bot é WebP. Esta verificação barata impede que
    // um arquivo regular colocado manualmente no volume seja servido como imagem.
    if (!webpEstruturalValido(dados)) {
      throw new Error("Arquivo local de mídia incompatível");
    }
    return { dados, tamanho: info.size };
  } finally {
    await arquivo.close();
  }
}

export function criarMidiaLocalModel(obterConfiguracao = async () => {
  const { env } = await import("../config/env.js");
  return { diretorio: env.midiaLocalDir, limiteBytes: env.midiaSaidaMaxBytes };
}) {
  return {
    async ler(chave) {
      validarChave(chave);
      const { diretorio, limiteBytes = LIMITE_PADRAO } = await obterConfiguracao();
      if (!diretorio) return null;
      const raiz = await abrirRaiz(diretorio);
      try {
        return await abrirRegular(raiz, diretorio, chave, limiteBytes);
      } finally {
        await raiz.close();
      }
    },

    async apagarChave(chave) {
      validarChave(chave);
      const { diretorio } = await obterConfiguracao();
      const raiz = await abrirRaiz(diretorio);
      const caminho = caminhoAncorado(raiz, diretorio, chave);
      try {
        let info;
        try {
          info = await fs.lstat(caminho);
        } catch (erro) {
          if (erro?.code === "ENOENT") return;
          throw erro;
        }
        if (!info.isFile() || info.isSymbolicLink()) {
          throw new Error("Arquivo local de mídia inseguro");
        }
        await fs.unlink(caminho);
      } finally {
        await raiz.close();
      }
    },
  };
}

export const MidiaLocalModel = criarMidiaLocalModel();
