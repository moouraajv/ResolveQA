"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CodeXml } from "lucide-react";

const links = [
  { href: "/", label: "Início" },
  { href: "/quadro", label: "Quadro" },
  { href: "/admin", label: "Admin" },
] as const;

export function SiteHeader({ demo = true }: { demo?: boolean }) {
  const path = usePathname();
  return (
    <header className="site-header">
      <Link className="brand" href="/" aria-label="Mola, início">
        <span className="brand-symbol">▥</span>MOLA
        <span className="brand-sub">agent workspace</span>
      </Link>
      <nav aria-label="Navegação principal">
        {links.map(n => (
          <Link key={n.href} className={path === n.href ? "active" : ""} href={n.href}>
            {n.label}
          </Link>
        ))}
      </nav>
      <div className="header-end">
        {demo ? (
          <span className="demo-badge">
            <span />
            Modo demonstração
          </span>
        ) : null}
        <a
          className="github-link"
          href="https://github.com/ThiagoVenturaV/ResolveQA-front"
          target="_blank"
          rel="noreferrer"
          aria-label="Abrir ResolveQA no GitHub"
        >
          <CodeXml size={19} />
        </a>
      </div>
    </header>
  );
}
