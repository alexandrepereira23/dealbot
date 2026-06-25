"use client";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRouter } from "next/navigation";

type Produto = {
  id: number;
  titulo: string;
  preco: number;
  preco_original: number | null;
  cupom: string | null;
  link: string | null;
  foto_url: string | null;
  categoria: string;
};

const CATEGORIAS = ["todos", "eletronicos", "casa", "moda", "alimentos", "beleza", "games"];

export default function Home() {
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [filtro, setFiltro] = useState("todos");
  const [carregando, setCarregando] = useState(true);
  const router = useRouter();

  // protege a rota: sem sessão, manda pro login
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) router.push("/login");
    });
  }, [router]);

  // carrega produtos (refaz quando muda o filtro)
  useEffect(() => {
    async function carregar() {
      setCarregando(true);
      let q = supabase.from("produtos").select("*").order("criado_em", { ascending: false }).limit(60);
      if (filtro !== "todos") q = q.eq("categoria", filtro);
      const { data } = await q;
      setProdutos(data || []);
      setCarregando(false);
    }
    carregar();

    // realtime: novos produtos aparecem sozinhos
    const canal = supabase
      .channel("produtos-novos")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "produtos" }, carregar)
      .subscribe();
    return () => { supabase.removeChannel(canal); };
  }, [filtro]);

  async function sair() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "1.5rem", fontFamily: "system-ui" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>🏷️ Dealbot</h1>
        <button onClick={sair} style={{ padding: "6px 14px", border: "1px solid #d6d3d1", borderRadius: 8, background: "#fff", cursor: "pointer" }}>Sair</button>
      </header>

      <div style={{ display: "flex", gap: 8, marginBottom: "1.5rem", flexWrap: "wrap" }}>
        {CATEGORIAS.map((c) => (
          <button key={c} onClick={() => setFiltro(c)}
            style={{
              padding: "6px 16px", borderRadius: 20, fontSize: 14, cursor: "pointer", textTransform: "capitalize",
              border: filtro === c ? "1px solid #1D9E75" : "1px solid #e7e5e4",
              background: filtro === c ? "#1D9E75" : "#fff",
              color: filtro === c ? "#fff" : "#666",
            }}>
            {c}
          </button>
        ))}
      </div>

      {carregando ? (
        <p style={{ color: "#999" }}>Carregando...</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 16 }}>
          {produtos.map((p) => (
            <div key={p.id} style={{ border: "1px solid #e7e5e4", borderRadius: 12, overflow: "hidden", background: "#fff" }}>
              {p.foto_url && <img src={p.foto_url} alt={p.titulo} style={{ width: "100%", height: 140, objectFit: "cover" }} />}
              <div style={{ padding: 12 }}>
                <span style={{ fontSize: 11, background: "#E6F1FB", color: "#185FA5", padding: "2px 8px", borderRadius: 20, textTransform: "capitalize" }}>{p.categoria}</span>
                <p style={{ fontSize: 14, fontWeight: 500, margin: "8px 0 6px", lineHeight: 1.4 }}>{p.titulo}</p>
                <p style={{ fontSize: 18, fontWeight: 500, color: "#1D9E75", margin: "0 0 8px" }}>
                  R$ {p.preco?.toFixed(2)}
                  {p.preco_original && <span style={{ fontSize: 12, color: "#999", textDecoration: "line-through", marginLeft: 6 }}>R$ {p.preco_original.toFixed(2)}</span>}
                </p>
                {p.cupom && (
                  <div style={{ fontSize: 12, color: "#0F6E56", background: "#E1F5EE", border: "1px dashed #5DCAA5", borderRadius: 6, padding: "4px 8px", marginBottom: 8, width: "fit-content" }}>
                    🎟️ {p.cupom}
                  </div>
                )}
                {p.link && (
                  <a href={p.link} target="_blank" rel="noopener noreferrer"
                    style={{ display: "block", textAlign: "center", padding: 8, background: "#1D9E75", color: "#fff", borderRadius: 8, textDecoration: "none", fontSize: 13, fontWeight: 500 }}>
                    Ver oferta →
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
