"use client";
import { useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRouter } from "next/navigation";

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
    else router.push("/");
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f5f4" }}>
      <div style={{ background: "#fff", padding: "2.5rem", borderRadius: 12, width: 320, border: "1px solid #e7e5e4" }}>
        <h2 style={{ margin: "0 0 1.5rem", fontWeight: 500 }}>Entrar</h2>
        <label style={{ fontSize: 13, color: "#666" }}>E-mail</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)}
          style={{ width: "100%", padding: 9, margin: "4px 0 14px", boxSizing: "border-box", borderRadius: 8, border: "1px solid #d6d3d1" }} />
        <label style={{ fontSize: 13, color: "#666" }}>Senha</label>
        <input type="password" value={senha} onChange={(e) => setSenha(e.target.value)}
          style={{ width: "100%", padding: 9, margin: "4px 0 16px", boxSizing: "border-box", borderRadius: 8, border: "1px solid #d6d3d1" }} />
        {erro && <p style={{ color: "#dc2626", fontSize: 13 }}>{erro}</p>}
        <button onClick={entrar} disabled={carregando}
          style={{ width: "100%", padding: 10, background: "#1D9E75", color: "#fff", border: "none", borderRadius: 8, fontWeight: 500, cursor: "pointer" }}>
          {carregando ? "Entrando..." : "Entrar"}
        </button>
      </div>
    </div>
  );
}
