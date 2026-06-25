"use client";
import { Produto } from "@/lib/types";

function desconto(p: Produto): number | null {
  if (!p.preco || !p.preco_original || p.preco_original <= p.preco) return null;
  return Math.round((1 - p.preco / p.preco_original) * 100);
}

export function ProdutoCard({ produto }: { produto: Produto }) {
  const off = desconto(produto);

  return (
    <article
      className="fade-in"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ position: "relative", aspectRatio: "4 / 3", background: "var(--surface-2)" }}>
        {produto.foto_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={produto.foto_url}
            alt={produto.titulo}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "grid",
              placeItems: "center",
              color: "var(--text-dim)",
              fontFamily: "var(--mono)",
              fontSize: 12,
            }}
          >
            sem foto
          </div>
        )}
        {off && (
          <span
            style={{
              position: "absolute",
              top: 10,
              left: 10,
              background: "var(--accent)",
              color: "#1a1205",
              fontFamily: "var(--mono)",
              fontWeight: 700,
              fontSize: 12,
              padding: "3px 8px",
              borderRadius: 6,
            }}
          >
            -{off}%
          </span>
        )}
      </div>

      <div style={{ padding: "14px 14px 16px", display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--text-dim)",
          }}
        >
          {produto.categoria}
        </span>

        <h3 style={{ fontSize: 14, fontWeight: 500, lineHeight: 1.4, flex: 1 }}>
          {produto.titulo}
        </h3>

        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 20, fontWeight: 700, color: "var(--accent)" }}>
            R$ {produto.preco?.toFixed(2) ?? "—"}
          </span>
          {produto.preco_original && (
            <span
              style={{
                fontFamily: "var(--mono)",
                fontSize: 12,
                color: "var(--text-dim)",
                textDecoration: "line-through",
              }}
            >
              {produto.preco_original.toFixed(2)}
            </span>
          )}
        </div>

        {produto.cupom && (
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              color: "var(--green)",
              border: "1px dashed var(--border)",
              borderRadius: 6,
              padding: "5px 8px",
              display: "flex",
              gap: 6,
            }}
          >
            <span style={{ color: "var(--text-dim)" }}>cupom</span>
            {produto.cupom}
          </div>
        )}

        {produto.link && (
          <a
            href={produto.link}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              marginTop: 4,
              textAlign: "center",
              padding: "9px",
              background: "transparent",
              border: "1px solid var(--accent)",
              color: "var(--accent)",
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            Ver oferta
          </a>
        )}
      </div>
    </article>
  );
}
