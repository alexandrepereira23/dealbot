import { z } from "zod";
import { FiltroModel } from "../models/filtro.model.js";
import { NaoEncontrado, RequisicaoInvalida } from "../utils/errors.js";

const filtroSchema = z.object({
  nome: z.string().min(1, "Nome é obrigatório"),
  palavras_chave: z.array(z.string()).default([]),
  palavras_bloqueio: z.array(z.string()).default([]),
  categoria: z.string().nullable().optional(),
  preco_max: z.number().positive().nullable().optional(),
  ativo: z.boolean().default(true),
});

export const FiltroService = {
  async listar() {
    return FiltroModel.listar();
  },

  async criar(dados) {
    const parsed = filtroSchema.safeParse(dados);
    if (!parsed.success) {
      throw RequisicaoInvalida(parsed.error.issues[0].message);
    }
    return FiltroModel.criar(parsed.data);
  },

  async atualizar(id, dados) {
    const parsed = filtroSchema.partial().safeParse(dados);
    if (!parsed.success) {
      throw RequisicaoInvalida(parsed.error.issues[0].message);
    }
    const atualizado = await FiltroModel.atualizar(id, parsed.data).catch(() => null);
    if (!atualizado) throw NaoEncontrado("Filtro não encontrado");
    return atualizado;
  },

  async remover(id) {
    await FiltroModel.remover(id);
  },
};
