"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [modo, setModo] = useState<"login" | "cadastro">("login");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro("");
    setCarregando(true);

    try {
      const { error } =
        modo === "login"
          ? await supabase.auth.signInWithPassword({ email, password: senha })
          : await supabase.auth.signUp({ email, password: senha });

      if (error) {
        setErro(error.message);
      } else {
        router.replace("/");
      }
    } catch {
      setErro("Falha ao conectar");
    } finally {
      setCarregando(false);
    }
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
      <form
        onSubmit={handleSubmit}
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: 32,
          width: "100%",
          maxWidth: 360,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <h1
          style={{
            fontFamily: "var(--mono)",
            fontWeight: 700,
            fontSize: 18,
            color: "var(--accent)",
            marginBottom: 8,
          }}
        >
          ▸ dealbot
        </h1>

        <label style={labelStyle}>email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="voce@email.com"
          required
          style={inputStyle}
        />

        <label style={labelStyle}>senha</label>
        <input
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          placeholder="••••••••"
          required
          minLength={6}
          style={inputStyle}
        />

        {erro && (
          <p style={{ color: "#e85d5d", fontSize: 13 }}>{erro}</p>
        )}

        <button
          type="submit"
          disabled={carregando}
          style={{
            padding: 10,
            background: "var(--accent)",
            color: "#1a1205",
            border: "none",
            borderRadius: 8,
            fontWeight: 600,
            fontSize: 13,
            opacity: carregando ? 0.6 : 1,
            cursor: "pointer",
          }}
        >
          {carregando
            ? "entrando..."
            : modo === "login"
              ? "entrar"
              : "criar conta"}
        </button>

        <button
          type="button"
          onClick={() => setModo(modo === "login" ? "cadastro" : "login")}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--text-dim)",
            fontSize: 12,
            fontFamily: "var(--mono)",
            cursor: "pointer",
          }}
        >
          {modo === "login"
            ? "nao tem conta? criar"
            : "ja tem conta? entrar"}
        </button>
      </form>
    </main>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  color: "var(--text-dim)",
  fontFamily: "var(--mono)",
  marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 11px",
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 13,
};
