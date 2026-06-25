"use client";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Produto } from "@/lib/types";
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
      <main style={wrap}>
        <p style={{ color: "var(--text-dim)", fontFamily: "var(--mono)", fontSize: 13 }}>
          verificando sessão...
        </p>
      </main>
    );
  }

  return (
    <main style={wrap}>
      <Header email={email} onSair={sair} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 12,
          marginBottom: 24,
        }}
      >
        <Metrica rotulo="total" valor={stats?.total ?? 0} />
        <Metrica rotulo="eletronicos" valor={stats?.porCategoria?.eletronicos ?? 0} />
        <Metrica rotulo="casa" valor={stats?.porCategoria?.casa ?? 0} />
        <Metrica rotulo="moda" valor={stats?.porCategoria?.moda ?? 0} />
      </div>

      <div style={{ marginBottom: 24 }}>
        <FiltroCategorias ativo={categoria} onChange={setCategoria} />
      </div>

      {erro && (
        <p style={{ color: "#e85d5d", fontSize: 13, marginBottom: 16 }}>{erro}</p>
      )}

      {carregando ? (
        <p style={{ color: "var(--text-dim)", fontFamily: "var(--mono)", fontSize: 13 }}>
          carregando ofertas...
        </p>
      ) : produtos.length === 0 ? (
        <div
          style={{
            border: "1px dashed var(--border)",
            borderRadius: "var(--radius)",
            padding: "48px 24px",
            textAlign: "center",
            color: "var(--text-dim)",
          }}
        >
          <p style={{ fontFamily: "var(--mono)", fontSize: 14, marginBottom: 6 }}>
            nenhuma oferta ainda
          </p>
          <p style={{ fontSize: 13 }}>
            O bot grava aqui assim que captar promoções nos canais monitorados.
          </p>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 16,
          }}
        >
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
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "14px 16px",
      }}
    >
      <div
        style={{
          fontFamily: "var(--mono)",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-dim)",
          marginBottom: 6,
        }}
      >
        {rotulo}
      </div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 24, fontWeight: 700 }}>
        {valor}
      </div>
    </div>
  );
}

const wrap: React.CSSProperties = {
  maxWidth: 1100,
  margin: "0 auto",
  padding: "0 24px 48px",
};
