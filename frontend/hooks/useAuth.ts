"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export function useAuth() {
  const [carregando, setCarregando] = useState(true);
  const [email, setEmail] = useState<string | null>(null);
  const [autenticado, setAutenticado] = useState(false);
  const [usuarioId, setUsuarioId] = useState<string | null>(null);
  const [sessaoVersao, setSessaoVersao] = useState(0);
  const router = useRouter();
  // undefined significa que nem a primeira ausência de sessão foi aplicada.
  const sessaoAplicada = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    let ativo = true;
    let eventoRecebido = false;
    function aplicar(sessao: Awaited<ReturnType<typeof supabase.auth.getSession>>["data"]["session"]) {
      if (!ativo) return;
      const chave = sessao ? `${sessao.user.id}:${sessao.access_token}` : null;
      if (chave === sessaoAplicada.current) {
        setCarregando(false);
        return;
      }
      sessaoAplicada.current = chave;
      if (!sessao) {
        setAutenticado(false);
        setUsuarioId(null);
        setEmail(null);
        setSessaoVersao((atual) => atual + 1);
        setCarregando(false);
        router.replace("/login");
      } else {
        setAutenticado(true);
        setUsuarioId(sessao.user.id);
        setEmail(sessao.user.email ?? null);
        setSessaoVersao((atual) => atual + 1);
        setCarregando(false);
      }
    }
    supabase.auth.getSession().then(({ data }) => {
      // A assinatura pode entregar um estado mais novo enquanto getSession ainda
      // resolve; nesse caso a promessa inicial nunca deve restaurar sessão velha.
      if (!eventoRecebido) aplicar(data.session);
    }).catch(() => {
      if (!eventoRecebido) aplicar(null);
    });
    const { data } = supabase.auth.onAuthStateChange((_evento, sessao) => {
      eventoRecebido = true;
      aplicar(sessao);
    });
    return () => {
      ativo = false;
      data.subscription.unsubscribe();
    };
  }, [router]);

  const sair = useCallback(async () => {
    // Interrompe polling no mesmo tick, sem aguardar a notificação assíncrona
    // do provedor de Auth para limpar a tela.
    setAutenticado(false);
    setUsuarioId(null);
    setEmail(null);
    setSessaoVersao((atual) => atual + 1);
    await supabase.auth.signOut();
    router.replace("/login");
  }, [router]);

  return { carregando, autenticado, usuarioId, email, sessaoVersao, sair };
}
