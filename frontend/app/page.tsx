"use client";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Produto, CATEGORIA_LABELS } from "@/lib/types";
import { Header } from "@/components/Header";
import { FiltroCategorias } from "@/components/FiltroCategorias";
import { ProdutoCard } from "@/components/ProdutoCard";

type Stats = { total: number; porCategoria: Record<string, number> };

export default function Home() {
  const { carregando: authCarregando, email, sair } = useAuth();
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [categoria, setCategoria] = useState("todos");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro("");
    try {
      const rota = categoria === "todos" ? "/produtos" : `/produtos?categoria=${categoria}`;
      const [lista, estat] = await Promise.all([
        api.get(rota),
        api.get("/produtos/estatisticas"),
      ]);
      setProdutos(lista);
      setStats(estat);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar");
    } finally {
      setCarregando(false);
    }
  }, [categoria]);

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
        <Metrica rotulo={CATEGORIA_LABELS.casa} valor={stats?.porCategoria?.casa ?? 0} />
        <Metrica rotulo={CATEGORIA_LABELS.moda} valor={stats?.porCategoria?.moda ?? 0} />
      </div>

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

function Metrica({ rotulo, valor }: { rotulo: string; valor: number }) {
  return (
    <div className="metric">
      <div className="metric__label">{rotulo}</div>
      <div className="metric__value">{valor}</div>
    </div>
  );
}
