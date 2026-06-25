"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(false);
  const router = useRouter();

  async function entrar() {
    setCarregando(true);
    setErro("");
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password: senha,
    });
    setCarregando(false);
    if (error) setErro("E-mail ou senha inválidos");
    else router.replace("/");
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
      }}
    >
      <div
        className="fade-in"
        style={{
          width: "100%",
          maxWidth: 360,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "32px 28px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontWeight: 700,
              fontSize: 18,
              color: "var(--accent)",
            }}
          >
            ▸ dealbot
          </span>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 28 }}>
          Painel de ofertas
        </p>

        <label style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>
          e-mail
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && entrar()}
          style={inputStyle}
        />

        <label style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>
          senha
        </label>
        <input
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && entrar()}
          style={inputStyle}
        />

        {erro && (
          <p style={{ color: "#e85d5d", fontSize: 13, marginBottom: 12 }}>{erro}</p>
        )}

        <button
          onClick={entrar}
          disabled={carregando}
          style={{
            width: "100%",
            padding: 11,
            background: "var(--accent)",
            color: "#1a1205",
            border: "none",
            borderRadius: 8,
            fontWeight: 600,
            fontSize: 14,
            marginTop: 6,
            opacity: carregando ? 0.6 : 1,
          }}
        >
          {carregando ? "entrando..." : "Entrar"}
        </button>
      </div>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  margin: "6px 0 16px",
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 14,
};
