import { supabase } from "./supabase";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3333/api";

async function comToken(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function tratar(res: Response) {
  if (!res.ok) {
    const corpo = await res.json().catch(() => ({}));
    throw new Error(corpo.erro || `Erro ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  async get(rota: string) {
    return tratar(await fetch(`${BASE}${rota}`, { headers: await comToken() }));
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
