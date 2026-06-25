"use client";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Filtro, CATEGORIAS } from "@/lib/types";
import { Header } from "@/components/Header";

type FormState = {
  nome: string;
  palavras_chave: string;
  palavras_bloqueio: string;
  categoria: string;
  preco_max: string;
};

const FORM_VAZIO: FormState = {
  nome: "",
  palavras_chave: "",
  palavras_bloqueio: "",
  categoria: "",
  preco_max: "",
};

export default function FiltrosPage() {
  const { carregando: authCarregando, email, sair } = useAuth();
  const [filtros, setFiltros] = useState<Filtro[]>([]);
  const [form, setForm] = useState<FormState>(FORM_VAZIO);
  const [editandoId, setEditandoId] = useState<number | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setFiltros(await api.get("/filtros"));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao carregar");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    if (!authCarregando) carregar();
  }, [authCarregando, carregar]);

  function paraLista(texto: string): string[] {
    return texto
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function salvar() {
    setErro("");
    if (!form.nome.trim()) {
      setErro("Dê um nome ao filtro");
      return;
    }
    setSalvando(true);
    const corpo = {
      nome: form.nome.trim(),
      palavras_chave: paraLista(form.palavras_chave),
      palavras_bloqueio: paraLista(form.palavras_bloqueio),
      categoria: form.categoria || null,
      preco_max: form.preco_max ? Number(form.preco_max) : null,
      ativo: true,
    };
    try {
      if (editandoId) {
        await api.put(`/filtros/${editandoId}`, corpo);
      } else {
        await api.post("/filtros", corpo);
      }
      setForm(FORM_VAZIO);
      setEditandoId(null);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao salvar");
    } finally {
      setSalvando(false);
    }
  }

  function editar(f: Filtro) {
    setEditandoId(f.id);
    setForm({
      nome: f.nome,
      palavras_chave: (f.palavras_chave || []).join(", "),
      palavras_bloqueio: (f.palavras_bloqueio || []).join(", "),
      categoria: f.categoria || "",
      preco_max: f.preco_max?.toString() || "",
    });
  }

  function cancelar() {
    setEditandoId(null);
    setForm(FORM_VAZIO);
  }

  async function alternarAtivo(f: Filtro) {
    try {
      await api.put(`/filtros/${f.id}`, { ativo: !f.ativo });
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao atualizar");
    }
  }

  async function remover(id: number) {
    try {
      await api.del(`/filtros/${id}`);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao remover");
    }
  }

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

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 340px) 1fr", gap: 28, alignItems: "start" }}>
        <section
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: 20,
            position: "sticky",
            top: 24,
          }}
        >
          <h2 style={{ fontSize: 14, fontFamily: "var(--mono)", marginBottom: 18, color: "var(--accent)" }}>
            {editandoId ? "editar filtro" : "novo filtro"}
          </h2>

          <Campo
            rotulo="nome"
            valor={form.nome}
            onChange={(v) => setForm({ ...form, nome: v })}
            placeholder="Ex: Eletrônicos baratos"
          />
          <Campo
            rotulo="palavras-chave (separe por vírgula)"
            valor={form.palavras_chave}
            onChange={(v) => setForm({ ...form, palavras_chave: v })}
            placeholder="fone, notebook, ssd"
          />
          <Campo
            rotulo="palavras de bloqueio"
            valor={form.palavras_bloqueio}
            onChange={(v) => setForm({ ...form, palavras_bloqueio: v })}
            placeholder="usado, recondicionado"
          />

          <label style={labelStyle}>categoria</label>
          <select
            value={form.categoria}
            onChange={(e) => setForm({ ...form, categoria: e.target.value })}
            style={inputStyle}
          >
            <option value="">qualquer</option>
            {CATEGORIAS.filter((c) => c !== "todos").map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>

          <Campo
            rotulo="preço máximo (R$)"
            valor={form.preco_max}
            onChange={(v) => setForm({ ...form, preco_max: v })}
            placeholder="3000"
            tipo="number"
          />

          {erro && <p style={{ color: "#e85d5d", fontSize: 13, marginBottom: 12 }}>{erro}</p>}

          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button
              onClick={salvar}
              disabled={salvando}
              style={{
                flex: 1,
                padding: 10,
                background: "var(--accent)",
                color: "#1a1205",
                border: "none",
                borderRadius: 8,
                fontWeight: 600,
                fontSize: 13,
                opacity: salvando ? 0.6 : 1,
              }}
            >
              {salvando ? "salvando..." : editandoId ? "atualizar" : "criar filtro"}
            </button>
            {editandoId && (
              <button
                onClick={cancelar}
                style={{
                  padding: "10px 16px",
                  background: "transparent",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  color: "var(--text-dim)",
                  fontSize: 13,
                }}
              >
                cancelar
              </button>
            )}
          </div>
        </section>

        <section>
          {carregando ? (
            <p style={{ color: "var(--text-dim)", fontFamily: "var(--mono)", fontSize: 13 }}>
              carregando filtros...
            </p>
          ) : filtros.length === 0 ? (
            <div
              style={{
                border: "1px dashed var(--border)",
                borderRadius: "var(--radius)",
                padding: "40px 24px",
                textAlign: "center",
                color: "var(--text-dim)",
              }}
            >
              <p style={{ fontFamily: "var(--mono)", fontSize: 14 }}>nenhum filtro criado</p>
              <p style={{ fontSize: 13, marginTop: 6 }}>
                Sem filtros, o bot aceita todas as ofertas dos canais.
              </p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {filtros.map((f) => (
                <article
                  key={f.id}
                  className="fade-in"
                  style={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: "16px 18px",
                    opacity: f.ativo ? 1 : 0.55,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <h3 style={{ fontSize: 15, fontWeight: 600 }}>{f.nome}</h3>
                    <div style={{ display: "flex", gap: 6 }}>
                      <BotaoMini onClick={() => alternarAtivo(f)}>
                        {f.ativo ? "pausar" : "ativar"}
                      </BotaoMini>
                      <BotaoMini onClick={() => editar(f)}>editar</BotaoMini>
                      <BotaoMini onClick={() => remover(f.id)} perigo>
                        excluir
                      </BotaoMini>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontFamily: "var(--mono)", fontSize: 12, color: "var(--text-dim)" }}>
                    {f.categoria && <span>cat: {f.categoria}</span>}
                    {f.preco_max && <span>max: R$ {Number(f.preco_max).toFixed(2)}</span>}
                    {f.palavras_chave?.length > 0 && (
                      <span style={{ color: "var(--green)" }}>+ {f.palavras_chave.join(", ")}</span>
                    )}
                    {f.palavras_bloqueio?.length > 0 && (
                      <span style={{ color: "#e85d5d" }}>− {f.palavras_bloqueio.join(", ")}</span>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function Campo({
  rotulo,
  valor,
  onChange,
  placeholder,
  tipo = "text",
}: {
  rotulo: string;
  valor: string;
  onChange: (v: string) => void;
  placeholder?: string;
  tipo?: string;
}) {
  return (
    <>
      <label style={labelStyle}>{rotulo}</label>
      <input
        type={tipo}
        value={valor}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={inputStyle}
      />
    </>
  );
}

function BotaoMini({
  children,
  onClick,
  perigo,
}: {
  children: React.ReactNode;
  onClick: () => void;
  perigo?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: "var(--mono)",
        fontSize: 11,
        padding: "4px 10px",
        background: "transparent",
        border: "1px solid var(--border)",
        borderRadius: 6,
        color: perigo ? "#e85d5d" : "var(--text-dim)",
      }}
    >
      {children}
    </button>
  );
}

const wrap: React.CSSProperties = {
  maxWidth: 1100,
  margin: "0 auto",
  padding: "0 24px 48px",
};

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
  margin: "0 0 14px",
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 13,
};
