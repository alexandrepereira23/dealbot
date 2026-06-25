"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export function useAuth() {
  const [carregando, setCarregando] = useState(true);
  const [email, setEmail] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.replace("/login");
      } else {
        setEmail(data.session.user.email ?? null);
        setCarregando(false);
      }
    });
  }, [router]);

  async function sair() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  return { carregando, email, sair };
}
