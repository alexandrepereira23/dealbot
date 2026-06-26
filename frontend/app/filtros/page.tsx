"use client";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Filtro, CATEGORIAS, CATEGORIA_LABELS } from "@/lib/types";
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
    return texto.split(",").map((s) => s.trim()).filter(Boolean);
  }

  async function salvar() {
    setErro("");
    if (!form.nome.trim()) {
      setErro("Dê um nome ao filtro.");
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
      <main className="container">
        <p className="state-loading">Verificando sessão…</p>
      </main>
    );
  }

  return (
    <main className="container">
      <Header email={email} onSair={sair} />

      <div className="filtros-layout">
        {/* Formulário */}
        <section className="filtros-form">
          <h2 className="section-title">
            {editandoId ? "Editar filtro" : "Novo filtro"}
          </h2>

          <Campo
            id="nome"
            rotulo="Nome"
            valor={form.nome}
            onChange={(v) => setForm({ ...form, nome: v })}
            placeholder="Ex.: Eletrônicos baratos"
          />
          <Campo
            id="palavras_chave"
            rotulo="Palavras-chave"
            ajuda="Separe por vírgula. Pelo menos uma deve aparecer no título."
            valor={form.palavras_chave}
            onChange={(v) => setForm({ ...form, palavras_chave: v })}
            placeholder="fone, notebook, ssd"
          />
          <Campo
            id="palavras_bloqueio"
            rotulo="Palavras de bloqueio"
            ajuda="Produtos com esses termos no título serão ignorados."
            valor={form.palavras_bloqueio}
            onChange={(v) => setForm({ ...form, palavras_bloqueio: v })}
            placeholder="usado, recondicionado"
          />

          <div className="field">
            <label className="label" htmlFor="categoria">Categoria</label>
            <select
              id="categoria"
              value={form.categoria}
              onChange={(e) => setForm({ ...form, categoria: e.target.value })}
              className="input"
            >
              <option value="">Qualquer</option>
              {CATEGORIAS.filter((c) => c !== "todos").map((c) => (
                <option key={c} value={c}>
                  {CATEGORIA_LABELS[c] ?? c}
                </option>
              ))}
            </select>
          </div>

          <Campo
            id="preco_max"
            rotulo="Preço máximo (R$)"
            valor={form.preco_max}
            onChange={(v) => setForm({ ...form, preco_max: v })}
            placeholder="3000"
            tipo="number"
          />

          {erro && <p className="error-text" style={{ marginBottom: 12 }}>{erro}</p>}

          <div className="form-actions">
            <button
              onClick={salvar}
              disabled={salvando}
              className="btn btn-primary"
              style={{ flex: 1 }}
            >
              {salvando ? "Salvando…" : editandoId ? "Atualizar" : "Criar filtro"}
            </button>
            {editandoId && (
              <button onClick={cancelar} className="btn btn-ghost">
                Cancelar
              </button>
            )}
          </div>
        </section>

        {/* Lista de filtros */}
        <section>
          {carregando ? (
            <p className="state-loading">Carregando filtros…</p>
          ) : filtros.length === 0 ? (
            <div className="empty">
              <p className="empty__title">Nenhum filtro criado</p>
              <p className="empty__body">
                Sem filtros, o bot aceita todas as ofertas dos canais monitorados.
              </p>
            </div>
          ) : (
            <div className="filtros-list">
              {filtros.map((f) => (
                <article
                  key={f.id}
                  className={`filtro fade-in${f.ativo ? "" : " is-paused"}`}
                >
                  <div className="filtro__head">
                    <h3 className="filtro__name">{f.nome}</h3>
                    <div className="filtro__actions">
                      <button
                        className="btn-mini"
                        onClick={() => alternarAtivo(f)}
                      >
                        {f.ativo ? "Pausar" : "Ativar"}
                      </button>
                      <button className="btn-mini" onClick={() => editar(f)}>
                        Editar
                      </button>
                      <button
                        className="btn-mini is-danger"
                        onClick={() => remover(f.id)}
                      >
                        Excluir
                      </button>
                    </div>
                  </div>
                  <div className="filtro__meta">
                    {f.categoria && (
                      <span>{CATEGORIA_LABELS[f.categoria] ?? f.categoria}</span>
                    )}
                    {f.preco_max && (
                      <span>Máx. R$ {Number(f.preco_max).toFixed(2)}</span>
                    )}
                    {f.palavras_chave?.length > 0 && (
                      <span className="is-keep">+ {f.palavras_chave.join(", ")}</span>
                    )}
                    {f.palavras_bloqueio?.length > 0 && (
                      <span className="is-block">− {f.palavras_bloqueio.join(", ")}</span>
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
  id,
  rotulo,
  ajuda,
  valor,
  onChange,
  placeholder,
  tipo = "text",
}: {
  id: string;
  rotulo: string;
  ajuda?: string;
  valor: string;
  onChange: (v: string) => void;
  placeholder?: string;
  tipo?: string;
}) {
  return (
    <div className="field">
      <label className="label" htmlFor={id}>{rotulo}</label>
      {ajuda && <span className="help">{ajuda}</span>}
      <input
        id={id}
        type={tipo}
        value={valor}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="input"
      />
    </div>
  );
}
