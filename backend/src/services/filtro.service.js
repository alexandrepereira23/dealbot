import { z } from "zod";
import { FiltroModel } from "../models/filtro.model.js";
import { NaoEncontrado, RequisicaoInvalida } from "../utils/errors.js";

const normalizarTermo = (termo) => termo.toLowerCase().normalize("NFD")
  .replace(/\p{Mn}/gu, "").replace(/\s+/gu, " ").trim();

// Conta casas na representação decimal transportada em JSON, não em float * 100.
function temPrecisaoDeCentavos(valor) {
  const [coeficiente, expoente = "0"] = String(valor).split("e");
  return (coeficiente.split(".")[1]?.length ?? 0) - Number(expoente) <= 2;
}

const termosSchema = z.array(z.string().trim().min(1, "Termo vazio")
  .max(100, "Cada termo deve ter até 100 caracteres"))
  .max(50, "Use até 50 termos por lista")
  .refine((termos) => termos.every((termo) => normalizarTermo(termo).length > 0),
    "Termo vazio após normalização")
  .refine((termos) => new Set(termos.map(normalizarTermo)).size === termos.length,
    "Termos duplicados após normalizar caixa, acentos e espaços");

// Sem defaults aqui: o schema parcial deve preservar campos omitidos.
const camposSchema = z.object({
  nome: z.string().trim().min(1, "Nome é obrigatório").max(100, "Nome deve ter até 100 caracteres"),
  palavras_chave: termosSchema,
  palavras_bloqueio: termosSchema,
  tipo_regra: z.enum(["interesse", "bloqueio_global"]),
  modo_palavras: z.enum(["qualquer", "todas"]),
  categoria: z.enum(["eletronicos", "casa", "moda", "alimentos", "beleza", "games", "outros"]).nullable(),
  preco_max: z.number().finite().min(0).max(99999999.99)
    .refine(temPrecisaoDeCentavos, "Preço deve ter no máximo duas casas decimais").nullable(),
  ativo: z.boolean(),
}).strict();

function validarGlobal(filtro, ctx) {
  if (filtro.tipo_regra !== "bloqueio_global") return;
  if (!filtro.palavras_bloqueio.length) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["palavras_bloqueio"],
      message: "Bloqueio global exige ao menos um termo de bloqueio" });
  }
  if (filtro.palavras_chave.length || filtro.categoria !== null || filtro.preco_max !== null) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["tipo_regra"],
      message: "Bloqueio global não permite palavras-chave, categoria ou preço máximo" });
  }
}

const filtroSchema = camposSchema.extend({
  palavras_chave: termosSchema.default([]),
  palavras_bloqueio: termosSchema.default([]),
  tipo_regra: camposSchema.shape.tipo_regra.default("interesse"),
  modo_palavras: camposSchema.shape.modo_palavras.default("qualquer"),
  categoria: camposSchema.shape.categoria.default(null),
  preco_max: camposSchema.shape.preco_max.default(null),
  ativo: z.boolean().default(true),
}).superRefine(validarGlobal);
const parcialSchema = camposSchema.partial().refine((dados) => Object.keys(dados).length > 0,
  "Informe ao menos um campo para atualizar");

function validar(schema, dados) {
  const parsed = schema.safeParse(dados);
  if (!parsed.success) throw RequisicaoInvalida(parsed.error.issues[0].message);
  return parsed.data;
}

export function criarFiltroService(model = FiltroModel) {
  return {
    async listar() {
      return model.listar();
    },

    async criar(dados) {
      return model.criar(validar(filtroSchema, dados));
    },

    async atualizar(id, dados) {
      const campos = validar(parcialSchema, dados);
      const atual = await model.buscarPorId(id);
      if (!atual) throw NaoEncontrado("Filtro não encontrado");
      // Campos de identificação não fazem parte do corpo editável.
      const existentes = Object.fromEntries(Object.keys(camposSchema.shape)
        .map((campo) => [campo, atual[campo]]));
      // Arrays NULL eram permitidos no schema legado e o bot os trata como
      // condição vazia. Validar assim não regrava campos omitidos no PUT.
      existentes.palavras_chave ??= [];
      existentes.palavras_bloqueio ??= [];
      validar(filtroSchema, { ...existentes, ...campos });
      const atualizado = await model.atualizar(id, campos);
      if (!atualizado) throw NaoEncontrado("Filtro não encontrado");
      return atualizado;
    },

    async remover(id) {
      await model.remover(id);
    },
  };
}

export const FiltroService = criarFiltroService();
