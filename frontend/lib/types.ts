export type Produto = {
  id: number;
  titulo: string;
  preco: number | null;
  preco_original: number | null;
  cupom: string | null;
  link: string | null;
  foto_url: string | null;
  categoria: string;
  canal_origem: string | null;
  criado_em: string;
  data_oferta: string | null;
};

export type Filtro = {
  id: number;
  nome: string;
  palavras_chave: string[];
  palavras_bloqueio: string[];
  categoria: string | null;
  preco_max: number | null;
  ativo: boolean;
};

export const CATEGORIAS = [
  "todos",
  "eletronicos",
  "casa",
  "moda",
  "alimentos",
  "beleza",
  "games",
  "outros",
] as const;

export const CATEGORIA_LABELS: Record<string, string> = {
  todos: "Todas",
  eletronicos: "Eletrônicos",
  casa: "Casa",
  moda: "Moda",
  alimentos: "Alimentos",
  beleza: "Beleza",
  games: "Games",
  outros: "Outros",
};
