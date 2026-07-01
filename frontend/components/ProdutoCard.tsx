"use client";
import { useState } from "react";
import { Produto } from "@/lib/types";

function desconto(p: Produto): number | null {
  if (!p.preco || !p.preco_original || p.preco_original <= p.preco) return null;
  return Math.round((1 - p.preco / p.preco_original) * 100);
}

function formatarData(produto: Produto): string | null {
  const fonte = produto.data_oferta ?? produto.criado_em;
  if (!fonte) return null;
  const d = new Date(fonte);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatarCanal(canal: string | null | undefined): string | null {
  if (!canal) return null;
  return /^\d+$/.test(canal) ? canal : `@${canal}`;
}

function listarCanais(produto: Produto): string[] {
  const fonte = produto.canais && produto.canais.length > 0
    ? produto.canais
    : produto.canal_origem
      ? [produto.canal_origem]
      : [];
  return fonte
    .map((c) => formatarCanal(c))
    .filter((c): c is string => c !== null);
}

export function ProdutoCard({ produto }: { produto: Produto }) {
  const [copiado, setCopiado] = useState(false);
  const off = desconto(produto);
  const dataFmt = formatarData(produto);
  const canais = listarCanais(produto);

  function copiarCupom() {
    if (!produto.cupom) return;
    navigator.clipboard.writeText(produto.cupom).then(() => {
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    });
  }

  return (
    <article className="produto fade-in">
      <div className="produto__media">
        {produto.foto_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={produto.foto_url}
            alt={produto.titulo}
            loading="lazy"
            decoding="async"
          />
        ) : (
          <div className="produto__no-photo">Sem foto</div>
        )}
        {off && <span className="produto__badge">-{off}%</span>}
      </div>
      <div className="produto__body">
        <div className="produto__meta">
          <span className="produto__eyebrow">{produto.categoria}</span>
          {dataFmt && <span className="produto__date">{dataFmt}</span>}
        </div>
        {canais.length > 0 && (
          <div className="produto__channels" title={canais.join(", ")}>
            <span className="produto__channel">{canais[0]}</span>
            {canais.length > 1 && (
              <span className="produto__channel-extra">+{canais.length - 1}</span>
            )}
          </div>
        )}
        <h3 className="produto__title">{produto.titulo}</h3>
        <div className="produto__prices">
          <span className="produto__price">
            R$ {produto.preco?.toFixed(2) ?? "—"}
          </span>
          {produto.preco_original && (
            <span className="produto__price-old">
              {produto.preco_original.toFixed(2)}
            </span>
          )}
        </div>
        {produto.cupom && (
          <div className="produto__coupon">
            <span>Cupom</span>
            <strong>{produto.cupom}</strong>
            <button
              onClick={copiarCupom}
              className="produto__coupon-copy"
              aria-label="Copiar cupom"
            >
              {copiado ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              )}
            </button>
          </div>
        )}
        {produto.link && (
          <a
            href={produto.link}
            target="_blank"
            rel="noopener noreferrer"
            className="produto__cta"
          >
            Ver oferta
          </a>
        )}
      </div>
    </article>
  );
}