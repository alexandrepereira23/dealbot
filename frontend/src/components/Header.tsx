"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function Header({ email, onSair }: { email: string | null; onSair: () => void }) {
  const path = usePathname();

  const links = [
    { href: "/", label: "ofertas" },
    { href: "/filtros", label: "filtros" },
  ];

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 0",
        borderBottom: "1px solid var(--border)",
        marginBottom: 28,
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontWeight: 700,
            fontSize: 16,
            color: "var(--accent)",
          }}
        >
          ▸ dealbot
        </span>
        <nav style={{ display: "flex", gap: 4 }}>
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              style={{
                fontFamily: "var(--mono)",
                fontSize: 13,
                padding: "5px 12px",
                borderRadius: 6,
                color: path === l.href ? "var(--text)" : "var(--text-dim)",
                background: path === l.href ? "var(--surface-2)" : "transparent",
              }}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>
          {email}
        </span>
        <button
          onClick={onSair}
          style={{
            fontFamily: "var(--mono)",
            fontSize: 12,
            padding: "5px 12px",
            background: "transparent",
            border: "1px solid var(--border)",
            borderRadius: 6,
            color: "var(--text-dim)",
          }}
        >
          sair
        </button>
      </div>
    </header>
  );
}
