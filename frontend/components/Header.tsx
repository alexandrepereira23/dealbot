"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

function LogoIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <rect width="26" height="26" rx="6" fill="#f0a030"/>
      <path d="M5 9.5h12l2.5 4-2.5 4H5l-1.5-4 1.5-4z" fill="#1a0e00"/>
      <circle cx="5.5" cy="13.5" r="1.8" fill="#1a0e00"/>
    </svg>
  );
}

export function Header({ email, onSair }: { email: string | null; onSair: () => void }) {
  const path = usePathname();
  const links = [
    { href: "/", label: "Ofertas" },
    { href: "/filtros", label: "Filtros" },
  ];
  return (
    <header className="site-header">
      <div className="site-header__group">
        <span className="brand">
          <LogoIcon />
          deal<span style={{ color: "#f0a030" }}>bot</span>
        </span>
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