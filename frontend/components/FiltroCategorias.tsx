"use client";
import { CATEGORIAS, CATEGORIA_LABELS } from "@/lib/types";

export function FiltroCategorias({
  ativo,
  onChange,
}: {
  ativo: string;
  onChange: (cat: string) => void;
}) {
  return (
    <div className="chips">
      {CATEGORIAS.map((cat) => (
        <button
          key={cat}
          onClick={() => onChange(cat)}
          className={`chip${ativo === cat ? " is-active" : ""}`}
        >
          {CATEGORIA_LABELS[cat] ?? cat}
        </button>
      ))}
    </div>
  );
}
