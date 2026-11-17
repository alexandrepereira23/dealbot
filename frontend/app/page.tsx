"use client";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { api, ErroApi } from "@/lib/api";
import { Produto, CATEGORIA_LABELS } from "@/lib/types";
import { Header } from "@/components/Header";
import { FiltroCategorias } from "@/components/FiltroCategorias";
import { ProdutoCard } from "@/components/ProdutoCard";
import { BuscaInput } from "@/components/BuscaInput";
import { atrasoExponencial, ControladorPolling, PortaoPolling } from "@/lib/polling";

type Stats = { total: number; porCategoria: Record<string, number> };
const TIMEOUT_MS = 10_000;
const TETO_RECUO_MS = 60_000;

function intervalo(configurado: string | undefined, padrao: number, minimo: number) {
  const valor = Number(configurado);
  return Number.isInteger(valor) && valor >= minimo && valor <= 300_000 ? valor : padrao;
}

// Referências diretas permitem ao Next substituir NEXT_PUBLIC_* no bundle;
// process.env[nome] dinâmico não é disponibilizado ao browser no build.
const INTERVALO_LISTA = intervalo(process.env.NEXT_PUBLIC_POLLING_LISTA_MS, 5_000, 5_000);
const INTERVALO_STATS = Math.max(INTERVALO_LISTA, intervalo(process.env.NEXT_PUBLIC_POLLING_STATS_MS, 30_000, 30_000));

function useAbaVisivel() {
  const [visivel, setVisivel] = useState(() => typeof document === "undefined" || !document.hidden);
  useEffect(() => {
    const atualizar = () => setVisivel(!document.hidden);
    document.addEventListener("visibilitychange", atualizar);
    return () => document.removeEventListener("visibilitychange", atualizar);
  }, []);
  return visivel;
}

function rotaLista(categoria: string, busca: string) {
  const params = new URLSearchParams();
  if (categoria !== "todos") params.set("categoria", categoria);
  if (busca.length >= 2) params.set("q", busca);
  const qs = params.toString();
  return qs ? `/produtos?${qs}` : "/produtos";
}

export default function Home() {
  const { carregando: authCarregando, autenticado, usuarioId, email, sessaoVersao, sair } = useAuth();
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [categoria, setCategoria] = useState("todos");
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [carregandoInicial, setCarregandoInicial] = useState(true);
  const [listaRecebida, setListaRecebida] = useState(false);
  const [erroLista, setErroLista] = useState("");
  const [erroStats, setErroStats] = useState("");
  const [atualizadoLista, setAtualizadoLista] = useState<number | null>(null);
  const visivel = useAbaVisivel();
  const listaRecebidaRef = useRef(false);
  const recuoLista = useRef(new PortaoPolling());
  const recuoStats = useRef(new PortaoPolling());
  const rateLimit = useRef(new PortaoPolling());
  const usuarioAnterior = useRef<string | null | undefined>(undefined);
  const grade = useRef<HTMLDivElement>(null);
  const ancora = useRef<{ id: string; topo: number } | null>(null);

  useEffect(() => {
    const id = window.setTimeout(() => setBuscaAplicada(busca.trim()), 300);
    return () => window.clearTimeout(id);
  }, [busca]);

  useEffect(() => {
    if (authCarregando) return;
    if (usuarioAnterior.current !== undefined && usuarioAnterior.current !== usuarioId) {
      listaRecebidaRef.current = false;
      setListaRecebida(false);
      setProdutos([]);
      setStats(null);
      setErroLista("");
      setErroStats("");
      setAtualizadoLista(null);
      setCarregandoInicial(Boolean(usuarioId));
      recuoLista.current.limpar();
      recuoStats.current.limpar();
      rateLimit.current.limpar();
    }
    usuarioAnterior.current = usuarioId;
  }, [authCarregando, usuarioId]);

  function marcarAncora() {
    const cartao = Array.from(grade.current?.querySelectorAll<HTMLElement>("[data-produto-id]") ?? [])
      .find((elemento) => elemento.getBoundingClientRect().bottom > 0);
    if (cartao) {
      ancora.current = { id: cartao.dataset.produtoId!, topo: cartao.getBoundingClientRect().top };
    }
  }

  useLayoutEffect(() => {
    const anterior = ancora.current;
    if (!anterior) return;
    ancora.current = null;
    const cartao = grade.current?.querySelector<HTMLElement>(`[data-produto-id="${anterior.id}"]`);
    if (cartao) window.scrollBy(0, cartao.getBoundingClientRect().top - anterior.topo);
  }, [produtos]);

  // Uma geração por endpoint torna inofensiva qualquer resposta que chegue depois
  // do cancelamento, de uma troca de filtro, logout ou refresh de sessão.
  useEffect(() => {
    if (authCarregando) return;
    if (!autenticado || !visivel) {
      if (!autenticado) {
        listaRecebidaRef.current = false;
        // Limpar dados protegidos imediatamente ao invalidar a sessão.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setListaRecebida(false);
        setProdutos([]);
        setStats(null);
        setErroLista("");
        setErroStats("");
        setAtualizadoLista(null);
        setCarregandoInicial(false);
      }
      return;
    }
    const rota = rotaLista(categoria, buscaAplicada);
    const controlador = new ControladorPolling<Produto[]>({
      intervalo: INTERVALO_LISTA,
      timeout: TIMEOUT_MS,
      recuo: recuoLista.current,
      compartilhado: rateLimit.current,
      antes: () => {
        if (!listaRecebidaRef.current) setCarregandoInicial(true);
      },
      executar: (signal) => api.get(rota, { signal }) as Promise<Produto[]>,
      sucesso: (lista) => {
        setCarregandoInicial(false);
        listaRecebidaRef.current = true;
        setListaRecebida(true);
        marcarAncora();
        setProdutos(lista);
        setErroLista("");
        setAtualizadoLista(Date.now());
      },
      falha: async (erro, tentativa) => {
        setCarregandoInicial(false);
        if (erro instanceof ErroApi && erro.status === 401) {
          await sair();
          return null;
        }
        setErroLista(erro instanceof Error ? erro.message : "Falha ao atualizar ofertas");
        const espera = erro instanceof ErroApi && erro.retryAfterMs !== null
          ? Math.max(atrasoExponencial(tentativa, INTERVALO_LISTA, TETO_RECUO_MS), erro.retryAfterMs)
          : atrasoExponencial(tentativa, INTERVALO_LISTA, TETO_RECUO_MS);
        return { espera, compartilhar: erro instanceof ErroApi && erro.status === 429 };
      },
    });
    controlador.iniciar();
    return () => {
      controlador.parar();
    };
  }, [authCarregando, autenticado, sessaoVersao, usuarioId, categoria, buscaAplicada, visivel, sair]);

  // Stats não compartilha falhas normais com a lista; apenas 429/Retry-After
  // bloqueia ambos, pois os dois endpoints consomem o mesmo orçamento por IP.
  useEffect(() => {
    if (authCarregando || !autenticado || !visivel) return;
    const controlador = new ControladorPolling<Stats>({
      intervalo: INTERVALO_STATS,
      timeout: TIMEOUT_MS,
      recuo: recuoStats.current,
      compartilhado: rateLimit.current,
      executar: (signal) => api.get("/produtos/estatisticas", { signal }) as Promise<Stats>,
      sucesso: (estat) => {
        setStats(estat);
        setErroStats("");
      },
      falha: async (erro, tentativa) => {
        if (erro instanceof ErroApi && erro.status === 401) {
          await sair();
          return null;
        }
        setErroStats(erro instanceof Error ? erro.message : "Falha ao atualizar métricas");
        const espera = erro instanceof ErroApi && erro.retryAfterMs !== null
          ? Math.max(atrasoExponencial(tentativa, INTERVALO_STATS, TETO_RECUO_MS), erro.retryAfterMs)
          : atrasoExponencial(tentativa, INTERVALO_STATS, TETO_RECUO_MS);
        return { espera, compartilhar: erro instanceof ErroApi && erro.status === 429 };
      },
    });
    controlador.iniciar();
    return () => {
      controlador.parar();
    };
  }, [authCarregando, autenticado, sessaoVersao, usuarioId, visivel, sair]);

  const { comCupom, menorPreco } = useMemo(() => {
    const precos = produtos.map((p) => p.preco).filter((preco): preco is number => preco !== null);
    return {
      comCupom: produtos.filter((p) => Boolean(p.cupom)).length,
      menorPreco: precos.length ? Math.min(...precos) : null,
    };
  }, [produtos]);

  if (authCarregando) {
    return <main className="container"><p className="state-loading">Verificando sessão…</p></main>;
  }
  if (!autenticado) {
    return <main className="container"><p className="state-loading">Redirecionando para entrar…</p></main>;
  }

  return (
    <main className="container">
      <Header email={email} onSair={sair} />
      <p className="metrics-note">Total e categorias são globais; cupom e menor preço refletem a lista exibida.</p>
      <div className="metrics">
        <Metrica rotulo="Total" valor={stats?.total ?? "—"} />
        <Metrica rotulo={CATEGORIA_LABELS.eletronicos} valor={stats ? stats.porCategoria.eletronicos ?? 0 : "—"} />
        <Metrica rotulo="Com cupom" valor={listaRecebida ? comCupom : "—"} />
        <Metrica rotulo="Menor preço" valor={menorPreco === null ? "—" : `R$ ${menorPreco.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`} />
      </div>
      <BuscaInput valor={busca} onChange={setBusca} />
      <FiltroCategorias ativo={categoria} onChange={setCategoria} />
      {erroLista && <p className="refresh-warning" role="status">Ofertas podem estar desatualizadas: {erroLista}</p>}
      {erroStats && <p className="refresh-warning" role="status">Métricas globais podem estar desatualizadas: {erroStats}</p>}
      {!erroLista && atualizadoLista && <p className="refresh-status" aria-live="polite">Atualizado automaticamente às {new Date(atualizadoLista).toLocaleTimeString("pt-BR")}</p>}
      {carregandoInicial ? (
        <p className="state-loading">Carregando ofertas…</p>
      ) : !listaRecebida ? (
        <p className="state-loading">Não foi possível consultar ofertas agora. A atualização será tentada novamente.</p>
      ) : produtos.length === 0 ? (
        <div className="empty">
          <p className="empty__title">Nenhuma oferta ainda</p>
          <p className="empty__body">O bot registra aqui assim que capturar promoções nos canais monitorados.</p>
        </div>
      ) : (
        <div className="grid-produtos" ref={grade}>
          {produtos.map((p) => <ProdutoCard key={p.id} produto={p} />)}
        </div>
      )}
    </main>
  );
}

function Metrica({ rotulo, valor }: { rotulo: string; valor: number | string }) {
  return <div className="metric"><div className="metric__label">{rotulo}</div><div className="metric__value">{valor}</div></div>;
}
