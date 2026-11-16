// Harness de hooks seguindo filtros.test.cjs, com rerender, deps e cleanup.
// Executa página/Auth/polling reais; não simula DOM, reconciliador ou layout.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function pendente() {
  let resolver, rejeitar;
  const promessa = new Promise((resolve, reject) => { resolver = resolve; rejeitar = reject; });
  return { promessa, resolver, rejeitar };
}

const sessao = (id = "usuario-a", token = "token-falso-a") => ({
  user: { id, email: `${id}@example.invalid` }, access_token: token,
});

function ambiente({ pagina = true, inicial = sessao(), adiarSessao = false, env = {}, apiReal = false, cardReal = false } = {}) {
  const slots = [];
  let cursor = 0, sujo = true, desmontado = false, arvore;
  let efeitos = [], layouts = [];
  const iguais = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const reactFalso = { ...React,
    useState(inicial) {
      const indice = cursor++;
      if (!(indice in slots)) slots[indice] = { valor: typeof inicial === "function" ? inicial() : inicial };
      return [slots[indice].valor, (valor) => {
        assert.equal(desmontado, false, "setState depois do unmount");
        const novo = typeof valor === "function" ? valor(slots[indice].valor) : valor;
        if (!Object.is(novo, slots[indice].valor)) { slots[indice].valor = novo; sujo = true; }
      }];
    },
    useRef(inicial) {
      const indice = cursor++;
      if (!(indice in slots)) slots[indice] = { current: inicial };
      return slots[indice];
    },
    useMemo(fn, deps) {
      const indice = cursor++;
      if (!iguais(slots[indice]?.deps, deps)) slots[indice] = { deps, valor: fn() };
      return slots[indice].valor;
    },
    useCallback(fn, deps) { return reactFalso.useMemo(() => fn, deps); },
    useEffect(fn, deps) { efeito(fn, deps, efeitos); },
    useLayoutEffect(fn, deps) { efeito(fn, deps, layouts); },
  };
  function efeito(fn, deps, fila) {
    const indice = cursor++;
    if (!iguais(slots[indice]?.deps, deps)) {
      const anterior = slots[indice];
      slots[indice] = { deps, efeito: fn, cleanup: anterior?.cleanup };
      fila.push(slots[indice]);
    }
  }
  function aplicar(fila) {
    for (const item of fila) item.cleanup?.();
    for (const item of fila) item.cleanup = item.efeito();
  }

  let agora = 1_000_000, proximo = 1;
  const timers = new Map();
  const janela = {
    setTimeout(callback, espera) {
      const id = proximo++;
      timers.set(id, { callback, quando: agora + espera });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    scrollBy() {},
  };
  const listeners = new Set();
  const documento = {
    hidden: false,
    addEventListener(nome, fn) { assert.equal(nome, "visibilitychange"); listeners.add(fn); },
    removeEventListener(nome, fn) { assert.equal(nome, "visibilitychange"); listeners.delete(fn); },
  };
  const redirecionamentos = [];
  const router = { replace: (rota) => redirecionamentos.push(rota) };
  const assinatura = new Set();
  const sessaoInicial = pendente();
  const logout = pendente();
  const consultasToken = [];
  let consultasSessao = 0;
  let saidas = 0;
  const supabase = { auth: {
    getSession: () => {
      consultasSessao += 1;
      if (!apiReal || consultasSessao === 1) return sessaoInicial.promessa;
      const consulta = pendente();
      consultasToken.push(consulta);
      return consulta.promessa;
    },
    onAuthStateChange(callback) {
      assinatura.add(callback);
      return { data: { subscription: { unsubscribe: () => assinatura.delete(callback) } } };
    },
    signOut() { saidas += 1; return logout.promessa; },
  } };
  if (!adiarSessao) sessaoInicial.resolver({ data: { session: inicial } });
  const chamadas = [];
  const api = { get(rota, { signal }) {
    const resposta = pendente();
    chamadas.push({ rota, signal, ...resposta });
    // Deliberadamente ignora abort: testa descarte pela geração real de polling.
    return resposta.promessa;
  } };
  class ErroApi extends Error {
    constructor(mensagem, status, retryAfterMs = null) { super(mensagem); Object.assign(this, { status, retryAfterMs }); }
  }
  // Componentes filhos são fronteiras falsas, não uma cópia da lógica da página.
  const componentes = {
    Header: () => null,
    BuscaInput: ({ valor, onChange }) => React.createElement("input", { value: valor, onChange }),
    FiltroCategorias: ({ ativo, onChange }) => React.createElement("select", { value: ativo, onChange }),
    ProdutoCard: ({ produto }) => React.createElement("article", { "data-produto-id": produto.id },
      produto.titulo, React.createElement("a", { href: produto.link }, "Ver oferta")),
  };
  const cache = new Map();
  function carregar(arquivo) {
    if (cache.has(arquivo)) return cache.get(arquivo);
    const absoluto = path.resolve(__dirname, "../..", arquivo);
    const compilado = ts.transpileModule(fs.readFileSync(absoluto, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
        target: ts.ScriptTarget.ES2020, esModuleInterop: true },
    }).outputText;
    const modulo = { exports: {} };
    cache.set(arquivo, modulo.exports);
    function importar(nome) {
      if (nome === "react") return arquivo.startsWith("components/") ? React : reactFalso;
      if (nome === "react/jsx-runtime") return require(nome);
      if (nome === "next/navigation") return { useRouter: () => router };
      if (nome === "@/lib/supabase" || nome === "./supabase") return { supabase };
      if (nome === "@/lib/api") return apiReal ? carregar("lib/api.ts") : { api, ErroApi };
      if (nome.startsWith("@/components/")) {
        const componente = nome.split("/").at(-1);
        assert.ok(componentes[componente]);
        if (cardReal && componente === "ProdutoCard") {
          componentes[componente] = carregar("components/ProdutoCard.tsx").ProdutoCard;
        }
        return { [componente]: componentes[componente] };
      }
      if (nome.startsWith("@/")) return carregar(`${nome.slice(2)}.ts`);
      throw new Error(`Importação offline inesperada: ${nome}`);
    }
    class DataFalsa extends Date { static now() { return agora; } }
    vm.runInNewContext(`(function(require,module,exports){${compilado}\n})`, {
      window: janela, document: documento, Date: DataFalsa, Error, AbortController, DOMException, URLSearchParams,
      fetch: (url, opcoes) => {
        assert.ok(apiReal, "rede não prevista neste harness");
        const resposta = pendente();
        const endereco = new URL(url);
        chamadas.push({ rota: endereco.pathname.replace(/^\/api/, "") + endereco.search,
          signal: opcoes.signal, headers: opcoes.headers, ...resposta });
        return resposta.promessa;
      },
      // Não herda process.env e não importa Supabase/configuração reais.
      process: { env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:54328/api", ...env } },
    }, { filename: absoluto })(importar, modulo, modulo.exports);
    return modulo.exports;
  }
  const executar = pagina ? carregar("app/page.tsx").default : carregar("hooks/useAuth.ts").useAuth;
  async function estabilizar() {
    for (let i = 0; i < 30; i += 1) {
      if (sujo && !desmontado) {
        sujo = false; cursor = 0; arvore = executar();
        const ls = layouts, es = efeitos;
        layouts = []; efeitos = [];
        aplicar(ls); aplicar(es);
      }
      await Promise.resolve();
    }
    assert.equal(sujo, false, "lifecycle deve estabilizar");
  }
  function elementos(no, resultado = []) {
    if (!no || typeof no !== "object") return resultado;
    if (Array.isArray(no)) { no.forEach((filho) => elementos(filho, resultado)); return resultado; }
    resultado.push(no);
    elementos(no.props?.children, resultado);
    return resultado;
  }
  return {
    chamadas, ErroApi: apiReal ? carregar("lib/api.ts").ErroApi : ErroApi,
    redirecionamentos, sessaoInicial, logout, consultasToken,
    estabilizar,
    estado: () => arvore,
    html: () => renderToStaticMarkup(arvore),
    cards: () => elementos(arvore).filter((no) => no.type === componentes.ProdutoCard),
    busca: () => elementos(arvore).find((no) => no.type === componentes.BuscaInput),
    categoria: () => elementos(arvore).find((no) => no.type === componentes.FiltroCategorias),
    pendencias: () => ({ timers: timers.size, listeners: listeners.size, assinaturas: assinatura.size, saidas }),
    async emitir(novaSessao, evento = "SIGNED_IN") {
      for (const callback of assinatura) callback(evento, novaSessao);
      await estabilizar();
    },
    async visibilidade(oculta) {
      documento.hidden = oculta;
      for (const callback of listeners) callback();
      await estabilizar();
    },
    async avancar(ms) {
      const fim = agora + ms;
      while (true) {
        const proximoTimer = [...timers.entries()].filter(([, timer]) => timer.quando <= fim)
          .sort((a, b) => a[1].quando - b[1].quando)[0];
        if (!proximoTimer) break;
        const [id, timer] = proximoTimer;
        agora = timer.quando; timers.delete(id); timer.callback();
        await estabilizar();
      }
      agora = fim;
      await estabilizar();
    },
    desmontar() {
      for (const slot of slots) slot?.cleanup?.();
      desmontado = true;
    },
  };
}

module.exports = { ambiente, sessao };
