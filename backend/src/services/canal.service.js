import { z } from "zod";
import { CanalModel } from "../models/canal.model.js";
import { NaoEncontrado, RequisicaoInvalida } from "../utils/errors.js";

const canalSchema = z.object({
  username: z
    .string()
    .min(2)
    .regex(/^@?[\w]+$/, "Username inválido"),
  ativo: z.boolean().default(true),
});

export const CanalService = {
  async listar() {
    return CanalModel.listar();
  },

  async criar(dados) {
    const parsed = canalSchema.safeParse(dados);
    if (!parsed.success) {
      throw RequisicaoInvalida(parsed.error.issues[0].message);
    }
    // normaliza para sempre ter @
    const username = parsed.data.username.startsWith("@")
      ? parsed.data.username
      : `@${parsed.data.username}`;
    return CanalModel.criar({ ...parsed.data, username });
  },

  async atualizar(id, dados) {
    const atualizado = await CanalModel.atualizar(id, dados).catch(() => null);
    if (!atualizado) throw NaoEncontrado("Canal não encontrado");
    return atualizado;
  },

  async remover(id) {
    await CanalModel.remover(id);
  },
};
