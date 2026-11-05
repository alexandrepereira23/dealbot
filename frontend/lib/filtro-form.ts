import { CATEGORIAS, Categoria, Filtro, ModoPalavras, TipoRegra } from "./types";

export type FormFiltro = {
  nome: string;
  palavras_chave: string;
  palavras_bloqueio: string;
  categoria: string;
  preco_max: string;
  tipo_regra: TipoRegra;
  modo_palavras: ModoPalavras;
};

export const FORM_VAZIO: FormFiltro = {
  nome: "", palavras_chave: "", palavras_bloqueio: "", categoria: "", preco_max: "",
  tipo_regra: "interesse", modo_palavras: "qualquer",
};

export function trocarTipo(form: FormFiltro, tipo_regra: TipoRegra): FormFiltro {
  return tipo_regra === "bloqueio_global"
    ? { ...form, tipo_regra, palavras_chave: "", categoria: "", preco_max: "" }
    : { ...form, tipo_regra };
}

export function formularioDoFiltro(filtro: Filtro): FormFiltro {
  return {
    nome: filtro.nome, palavras_chave: (filtro.palavras_chave ?? []).join(", "),
    palavras_bloqueio: (filtro.palavras_bloqueio ?? []).join(", "),
    categoria: filtro.categoria ?? "", preco_max: filtro.preco_max?.toString() ?? "",
    tipo_regra: filtro.tipo_regra, modo_palavras: filtro.modo_palavras,
  };
}

function paraLista(texto: string): string[] {
  const termos = texto.split(",").map((termo) => termo.trim()).filter(Boolean);
  if (termos.length > 50 || termos.some((termo) => termo.length > 100)) {
    throw new Error("Use até 50 termos por lista, com até 100 caracteres cada.");
  }
  const normalizados = termos.map((termo) => termo.toLowerCase().normalize("NFD")
    .replace(/\p{Mn}/gu, "").replace(/\s+/gu, " ").trim());
  if (normalizados.some((termo) => !termo)) throw new Error("Termo vazio após normalização.");
  if (new Set(normalizados).size !== termos.length) {
    throw new Error("Remova termos duplicados (caixa, acentos e espaços são equivalentes).");
  }
  return termos;
}

// Sem ativo: criação usa o default; edição de conteúdo nunca reativa regra pausada.
export function corpoDoFormulario(form: FormFiltro): Omit<Filtro, "id" | "ativo"> {
  const nome = form.nome.trim();
  if (!nome || nome.length > 100) throw new Error("Dê um nome ao filtro com 1 a 100 caracteres.");
  const palavras_chave = paraLista(form.palavras_chave);
  const palavras_bloqueio = paraLista(form.palavras_bloqueio);
  const preco_max = form.preco_max === "" ? null : Number(form.preco_max);
  if (preco_max !== null && (!Number.isFinite(preco_max) || preco_max < 0
    || preco_max > 99999999.99 || !/^(?:\d+(?:\.\d{0,2})?|\.\d{1,2})$/.test(form.preco_max))) {
    throw new Error("Preço deve estar entre 0 e 99.999.999,99, com até duas casas decimais.");
  }
  if (form.categoria && !(CATEGORIAS as readonly string[]).filter((c) => c !== "todos").includes(form.categoria)) {
    throw new Error("Categoria inválida.");
  }
  if (form.tipo_regra === "bloqueio_global"
    && (!palavras_bloqueio.length || palavras_chave.length || form.categoria || preco_max !== null)) {
    throw new Error("Bloqueio global exige termos de bloqueio e nenhuma inclusão, categoria ou teto.");
  }
  return { nome, palavras_chave, palavras_bloqueio, categoria: (form.categoria || null) as Categoria | null,
    preco_max, tipo_regra: form.tipo_regra, modo_palavras: form.modo_palavras };
}
