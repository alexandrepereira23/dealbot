"use client";
import { CATEGORIAS } from "@/lib/types";

export function FiltroCategorias({
  ativo,
  onChange,
}: {
  ativo: string;
  onChange: (cat: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {CATEGORIAS.map((cat) => {
        const selecionado = ativo === cat;
        return (
          <button
            key={cat}
            onClick={() => onChange(cat)}
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              padding: "6px 14px",
              borderRadius: 20,
              border: selecionado ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: selecionado ? "var(--accent)" : "transparent",
              color: selecionado ? "#1a1205" : "var(--text-dim)",
              fontWeight: selecionado ? 700 : 400,
              transition: "all 0.15s",
            }}
          >
            {cat}
          </button>
        );
      })}
    </div>
  );
}
