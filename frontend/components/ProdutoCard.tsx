"use client";
import { Produto } from "@/lib/types";

function desconto(p: Produto): number | null {
  if (!p.preco || !p.preco_original || p.preco_original <= p.preco) return null;
  return Math.round((1 - p.preco / p.preco_original) * 100);
}

export function ProdutoCard({ produto }: { produto: Produto }) {
  const off = desconto(produto);

  return (
    <article className="produto fade-in">
      <div className="produto__media">
        {produto.foto_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={produto.foto_url} alt={produto.titulo} />
        ) : (
          <div className="produto__no-photo">Sem foto</div>
        )}
        {off && <span className="produto__badge">-{off}%</span>}
      </div>

      <div className="produto__body">
        <span className="produto__eyebrow">{produto.categoria}</span>

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
            {produto.cupom}
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
