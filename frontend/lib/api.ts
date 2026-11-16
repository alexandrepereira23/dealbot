import { supabase } from "./supabase";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3333/api";

export class ErroApi extends Error {
  constructor(message: string, readonly status: number, readonly retryAfterMs: number | null) {
    super(message);
    this.name = "ErroApi";
  }
}

type EsperaToken = { resolver: (headers: HeadersInit) => void; rejeitar: (erro: unknown) => void };
const esperandoToken = new Set<EsperaToken>();
let consultandoSessao = false;

function consultarProximoLote() {
  if (consultandoSessao || esperandoToken.size === 0) return;
  consultandoSessao = true;
  void Promise.resolve().then(async () => {
    // Fecha o lote imediatamente antes da chamada SDK, sem await entre os dois.
    // Quem chega depois (inclusive outra sessão) nunca recebe este resultado.
    const lote = [...esperandoToken];
    if (lote.length === 0) return;
    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      const headers = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
      for (const consumidor of lote) {
        if (esperandoToken.has(consumidor)) consumidor.resolver(headers);
      }
    } catch (erro) {
      for (const consumidor of lote) {
        if (esperandoToken.has(consumidor)) consumidor.rejeitar(erro);
      }
    }
  }).finally(() => {
    consultandoSessao = false;
    // Uma nova consulta, só após concluir a anterior e apenas se restar alguém.
    consultarProximoLote();
  });
}

function comToken(signal?: AbortSignal): Promise<HeadersInit> {
  signal?.throwIfAborted();
  // getSession não aceita AbortSignal. Cancelar retira somente o consumidor;
  // uma única consulta SDK fica em curso, sem acumular consultas por retry.
  return new Promise((resolve, reject) => {
    const limpar = () => {
      esperandoToken.delete(espera);
      signal?.removeEventListener("abort", abortar);
    };
    const espera: EsperaToken = {
      resolver: headers => { limpar(); resolve(headers); },
      rejeitar: erro => { limpar(); reject(erro); },
    };
    const abortar = () => espera.rejeitar(signal?.reason ?? new DOMException("Consulta cancelada", "AbortError"));
    esperandoToken.add(espera);
    signal?.addEventListener("abort", abortar, { once: true });
    consultarProximoLote();
  });
}

function retryAfterMs(valor: string | null): number | null {
  if (!valor) return null;
  const segundos = Number(valor);
  if (Number.isFinite(segundos) && segundos >= 0) return segundos * 1000;
  const data = Date.parse(valor);
  return Number.isNaN(data) ? null : Math.max(0, data - Date.now());
}

async function tratar(res: Response) {
  if (!res.ok) {
    const corpo = await res.json().catch(() => ({}));
    throw new ErroApi(corpo.erro || `Erro ${res.status}`, res.status,
      retryAfterMs(res.headers.get("Retry-After")));
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  async get(rota: string, opcoes: { signal?: AbortSignal } = {}) {
    const headers = await comToken(opcoes.signal);
    opcoes.signal?.throwIfAborted();
    return tratar(await fetch(`${BASE}${rota}`, {
      headers, signal: opcoes.signal, cache: "no-store",
    }));
  },
  async post(rota: string, corpo: unknown) {
    return tratar(
      await fetch(`${BASE}${rota}`, {
        method: "POST",
        headers: await comToken(),
        body: JSON.stringify(corpo),
      })
    );
  },
  async put(rota: string, corpo: unknown) {
    return tratar(
      await fetch(`${BASE}${rota}`, {
        method: "PUT",
        headers: await comToken(),
        body: JSON.stringify(corpo),
      })
    );
  },
  async del(rota: string) {
    return tratar(
      await fetch(`${BASE}${rota}`, {
        method: "DELETE",
        headers: await comToken(),
      })
    );
  },
};
