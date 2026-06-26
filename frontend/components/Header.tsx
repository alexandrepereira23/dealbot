"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function Header({ email, onSair }: { email: string | null; onSair: () => void }) {
  const path = usePathname();

  const links = [
    { href: "/", label: "Ofertas" },
    { href: "/filtros", label: "Filtros" },
  ];

  return (
    <header className="site-header">
      <div className="site-header__group">
        <span className="brand">▸ Dealbot</span>
        <nav className="nav">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`nav-link${path === l.href ? " is-active" : ""}`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="site-header__account">
        {email && <span className="site-header__email">{email}</span>}
        <button onClick={onSair} className="btn btn-ghost">
          Sair
        </button>
      </div>
    </header>
  );
}
