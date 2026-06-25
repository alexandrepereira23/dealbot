"use client";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Produto, CATEGORIAS } from "@/lib/types";
import { Header } from "@/components/Header";
import { ProdutoCard } from "@/components/ProdutoCard";
import { FiltroCategorias } from "@/components/FiltroCategorias";

export default function HomePage() {
  const { carregando: authCarregando, email, sair } = useAuth();
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [categoria, setCategoria] = useState("todos");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const query = categoria !== "todos" ? `?categoria=${categoria}` : "";
      setProdutos(await api.get(`/ofertas${query}`));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar ofertas");
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
          verificando sessao...
        </p>
      </main>
    );
  }

  return (
    <main style={wrap}>
      <Header email={email} onSair={sair} />

      <FiltroCategorias ativo={categoria} onChange={setCategoria} />

      {erro && (
        <p style={{ color: "#e85d5d", fontSize: 13, marginTop: 16 }}>{erro}</p>
      )}

      <div
        style={{
          marginTop: 24,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          gap: 16,
        }}
      >
        {carregando ? (
          <p style={{ color: "var(--text-dim)", fontFamily: "var(--mono)", fontSize: 13 }}>
            carregando ofertas...
          </p>
        ) : produtos.length === 0 ? (
          <div
            style={{
              gridColumn: "1 / -1",
              border: "1px dashed var(--border)",
              borderRadius: "var(--radius)",
              padding: "48px 24px",
              textAlign: "center",
              color: "var(--text-dim)",
            }}
          >
            <p style={{ fontFamily: "var(--mono)", fontSize: 14 }}>
              nenhuma oferta encontrada
            </p>
          </div>
        ) : (
          produtos.map((p) => <ProdutoCard key={p.id} produto={p} />)
        )}
      </div>
    </main>
  );
}

const wrap: React.CSSProperties = {
  maxWidth: 1100,
  margin: "0 auto",
  padding: "0 24px 48px",
};
