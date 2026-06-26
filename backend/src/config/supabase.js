import { createClient } from "@supabase/supabase-js";
import { env } from "./env.js";
import ws from "ws";

// Cliente com SERVICE ROLE: ignora RLS, usado para ler/gravar dados.
export const supabaseAdmin = createClient(
  env.supabaseUrl,
  env.supabaseServiceKey,
  {
    auth: { persistSession: false },
    realtime: { transport: ws },
  }
);

// Cliente com ANON KEY: usado só para validar tokens de usuário.
export const supabaseAuth = createClient(
  env.supabaseUrl,
  env.supabaseAnonKey,
  {
    auth: { persistSession: false },
    realtime: { transport: ws },
  }
);