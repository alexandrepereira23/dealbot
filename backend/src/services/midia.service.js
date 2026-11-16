import { MidiaLocalModel } from "../models/midia-local.model.js";

export function criarMidiaService(model = MidiaLocalModel) {
  return {
    async buscar(chave) {
      return model.ler(chave);
    },
  };
}

export const MidiaService = criarMidiaService();
