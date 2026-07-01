"use client";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Produto, CATEGORIA_LABELS } from "@/lib/types";
import { Header } from "@/components/Header";
import { FiltroCategorias } from "@/components/FiltroCategorias";
import { ProdutoCard } from "@/components/ProdutoCard";
import { BuscaInput } from "@/components/BuscaInput";

type Stats = { total: number; porCategoria: Record<string, number> };

export default function Home() {
  const { carregando: authCarregando, email, sair } = useAuth();
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [comCupom, setComCupom] = useState(0);
  const [menorPreco, setMenorPreco] = useState<number | null>(null);
  const [categoria, setCategoria] = useState("todos");
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  // Debounce: aplica a busca 300ms depois que o usuário para de digitar.
  useEffect(() => {
    const id = setTimeout(() => setBuscaAplicada(busca.trim()), 300);
    return () => clearTimeout(id);
  }, [busca]);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro("");
    try {
      const params = new URLSearchParams();
      if (categoria && categoria !== "todos") params.set("categoria", categoria);
      if (buscaAplicada.length >= 2) params.set("q", buscaAplicada);
      const qs = params.toString();
      const rota = qs ? `/produtos?${qs}` : "/produtos";
      const [lista, estat] = await Promise.all([
        api.get(rota),
        api.get("/produtos/estatisticas"),
      ]);
      setProdutos(lista);
      setStats(estat);
      // calcula métricas extras a partir da lista
      const cupons = (lista as Produto[]).filter((p) => p.cupom).length;
      const precos = (lista as Produto[]).map((p) => p.preco).filter(Boolean) as number[];
      setComCupom(cupons);
      setMenorPreco(precos.length ? Math.min(...precos) : null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar");
    } finally {
      setCarregando(false);
    }
  }, [categoria, buscaAplicada]);

  useEffect(() => {
    if (!authCarregando) carregar();
  }, [authCarregando, carregar]);

  if (authCarregando) {
    return (
      <main className="container">
        <p className="state-loading">Verificando sessão…</p>
      </main>
    );
  }

  return (
    <main className="container">
      <Header email={email} onSair={sair} />
      <div className="metrics">
        <Metrica rotulo="Total" valor={stats?.total ?? 0} />
        <Metrica rotulo={CATEGORIA_LABELS.eletronicos} valor={stats?.porCategoria?.eletronicos ?? 0} />
        <Metrica rotulo="Com cupom" valor={comCupom} />
        <Metrica
          rotulo="Menor preço"
          valor={menorPreco ? `R$ ${menorPreco.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—"}
        />
      </div>
      <BuscaInput valor={busca} onChange={setBusca} />
      <FiltroCategorias ativo={categoria} onChange={setCategoria} />
      {erro && <p className="error-text" style={{ marginBottom: 16 }}>{erro}</p>}
      {carregando ? (
        <p className="state-loading">Carregando ofertas…</p>
      ) : produtos.length === 0 ? (
        <div className="empty">
          <p className="empty__title">Nenhuma oferta ainda</p>
          <p className="empty__body">
            O bot registra aqui assim que capturar promoções nos canais monitorados.
          </p>
        </div>
      ) : (
        <div className="grid-produtos">
          {produtos.map((p) => (
            <ProdutoCard key={p.id} produto={p} />
          ))}
        </div>
      )}
    </main>
  );
}

function Metrica({ rotulo, valor }: { rotulo: string; valor: number | string }) {
  return (
    <div className="metric">
      <div className="metric__label">{rotulo}</div>
      <div className="metric__value">{valor}</div>
    </div>
  );
}