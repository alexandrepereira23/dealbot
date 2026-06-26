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
      setErro("Falha ao conectar. Tente novamente.");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <main className="center-screen">
      <form onSubmit={handleSubmit} className="auth-card">
        <div>
          <p className="auth-card__brand">▸ Dealbot</p>
          <p className="auth-card__subtitle">
            {modo === "login" ? "Acesse seu painel" : "Crie sua conta"}
          </p>
        </div>

        <div className="field">
          <label className="label" htmlFor="email">E-mail</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="voce@email.com"
            required
            className="input"
          />
        </div>

        <div className="field">
          <label className="label" htmlFor="senha">Senha</label>
          <input
            id="senha"
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            placeholder="••••••••"
            required
            minLength={6}
            className="input"
          />
        </div>

        {erro && <p className="error-text">{erro}</p>}

        <button
          type="submit"
          disabled={carregando}
          className="btn btn-primary btn-block"
        >
          {carregando ? "Entrando…" : modo === "login" ? "Entrar" : "Criar conta"}
        </button>

        <button
          type="button"
          onClick={() => setModo(modo === "login" ? "cadastro" : "login")}
          className="btn-link btn-block"
          style={{ textAlign: "center" }}
        >
          {modo === "login"
            ? "Não tem conta? Criar uma"
            : "Já tem conta? Entrar"}
        </button>
      </form>
    </main>
  );
}
