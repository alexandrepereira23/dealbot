"use client";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { Filtro, CATEGORIAS, CATEGORIA_LABELS, TipoRegra, ModoPalavras } from "@/lib/types";
import { Header } from "@/components/Header";
import { FormFiltro, FORM_VAZIO, corpoDoFormulario, formularioDoFiltro, trocarTipo } from "@/lib/filtro-form";

export default function FiltrosPage() {
  const { carregando: authCarregando, email, sair } = useAuth();
  const [filtros, setFiltros] = useState<Filtro[]>([]);
  const [form, setForm] = useState<FormFiltro>(FORM_VAZIO);
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

  async function salvar() {
    setErro("");
    setSalvando(true);
    try {
      const corpo = corpoDoFormulario(form);
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
    setForm(formularioDoFiltro(f));
  }

  function cancelar() {
    setEditandoId(null);
    setForm(FORM_VAZIO);
  }

  async function alternarAtivo(f: Filtro) {
    setErro("");
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

          <p className="help">
            A descrição completa da oferta é avaliada, não só o título. Uma das regras de interesse
            ativas basta (OU); dentro de cada regra, palavras, categoria e teto se combinam (E).
            Preço desconhecido não passa em regra com teto; zero permite apenas gratuidade conhecida.
            Sem interesses ativos, ofertas válidas são aceitas se nenhum bloqueio global vetar.
          </p>

          <div className="field">
            <label className="label" htmlFor="tipo_regra">Tipo de regra</label>
            <select id="tipo_regra" className="input" value={form.tipo_regra}
              onChange={(e) => setForm(trocarTipo(form, e.target.value as TipoRegra))}>
              <option value="interesse">Interesse</option>
              <option value="bloqueio_global">Bloqueio global</option>
            </select>
            <span className="help">
              Ao escolher bloqueio global, palavras-chave, categoria e teto são limpos explicitamente.
              Nenhum interesse pode sobrepor um veto global.
            </span>
          </div>

          <div className="field">
            <label className="label" htmlFor="modo_palavras">
              Modo das palavras {form.tipo_regra === "bloqueio_global" ? "de bloqueio" : "de inclusão"}
            </label>
            <select id="modo_palavras" className="input" value={form.modo_palavras}
              onChange={(e) => setForm({ ...form, modo_palavras: e.target.value as ModoPalavras })}>
              <option value="qualquer">Qualquer termo</option>
              <option value="todas">Todos os termos</option>
            </select>
          </div>

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
            ajuda="Separe palavras ou frases por vírgula (até 50, até 100 caracteres cada). Qualquer/todas se aplica às inclusões na descrição completa; vazio não restringe."
            desabilitado={form.tipo_regra === "bloqueio_global"}
            valor={form.palavras_chave}
            onChange={(v) => setForm({ ...form, palavras_chave: v })}
            placeholder="fone, notebook, ssd"
          />
          <Campo
            id="palavras_bloqueio"
            rotulo="Palavras de bloqueio"
            ajuda={form.tipo_regra === "bloqueio_global"
              ? "Veto global na descrição completa: exige qualquer/todos os termos conforme o modo escolhido. Ao menos um termo é obrigatório."
              : "Veto somente desta regra, sempre por qualquer termo, mesmo no modo todas. Outro interesse ainda pode aceitar."}
            valor={form.palavras_bloqueio}
            onChange={(v) => setForm({ ...form, palavras_bloqueio: v })}
            placeholder="usado, recondicionado"
          />

          <div className="field">
            <label className="label" htmlFor="categoria">Categoria</label>
            <select
              id="categoria"
              value={form.categoria}
              disabled={form.tipo_regra === "bloqueio_global"}
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
            desabilitado={form.tipo_regra === "bloqueio_global"}
          />

          {erro && <p role="alert" className="error-text" style={{ marginBottom: 12 }}>{erro}</p>}

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
          ) : filtros.length === 0 && !erro ? (
            <div className="empty">
              <p className="empty__title">Nenhum filtro criado</p>
              <p className="empty__body">
                Sem regras ativas, o bot aceita todas as ofertas válidas dos canais monitorados.
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
                    <span>{f.tipo_regra === "bloqueio_global" ? "Bloqueio global" : "Interesse"}</span>
                    <span>{f.modo_palavras === "todas" ? "Todos os termos" : "Qualquer termo"}
                      {f.tipo_regra === "bloqueio_global" ? " de bloqueio" : " de inclusão"}</span>
                    {!f.ativo && <span>Pausado</span>}
                    {f.categoria && (
                      <span>{CATEGORIA_LABELS[f.categoria] ?? f.categoria}</span>
                    )}
                    {f.preco_max !== null && (
                      <span>Máx. R$ {Number(f.preco_max).toFixed(2)}</span>
                    )}
                    {f.palavras_chave?.length > 0 && (
                      <span className="is-keep">+ {f.palavras_chave.join(", ")}</span>
                    )}
                    {f.palavras_bloqueio?.length > 0 && (
                      <span className="is-block">
                        {f.tipo_regra === "bloqueio_global" ? "Veto global" : "Veto local (qualquer)"}: {f.palavras_bloqueio.join(", ")}
                      </span>
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
  desabilitado = false,
}: {
  id: string;
  rotulo: string;
  ajuda?: string;
  valor: string;
  onChange: (v: string) => void;
  placeholder?: string;
  tipo?: string;
  desabilitado?: boolean;
}) {
  return (
    <div className="field">
      <label className="label" htmlFor={id}>{rotulo}</label>
      {ajuda && <span className="help">{ajuda}</span>}
      <input
        id={id}
        type={tipo}
        disabled={desabilitado}
        maxLength={id === "nome" ? 100 : undefined}
        min={tipo === "number" ? 0 : undefined}
        max={tipo === "number" ? 99999999.99 : undefined}
        step={tipo === "number" ? "0.01" : undefined}
        value={valor}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="input"
      />
    </div>
  );
}
