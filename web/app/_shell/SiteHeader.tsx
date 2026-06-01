"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";

import { useBreadcrumb, type Crumb } from "./breadcrumb";

// Path-derived fallback so the breadcrumb shows the correct depth even before a page registers
// friendly labels (or if it never does). Uses the raw URL segment as the label.
function fallbackCrumbs(pathname: string): Crumb[] {
  const parts = pathname.split("/").filter(Boolean);
  const crumbs: Crumb[] = [];
  if (parts[0] && parts[0] !== "api") {
    crumbs.push({ label: parts[0], href: `/${parts[0]}` });
    if (parts[1]) {
      crumbs.push({ label: decodeURIComponent(parts[1]) });
    }
  }
  return crumbs;
}

// The persistent app shell (0013 u1): a slim header on every page. Doen branding links home,
// a context-aware breadcrumb shows depth (Doen / Doen -> Project / Doen -> Project -> Initiative),
// and a right slot is reserved for future auth controls (0007). It frames content, never competes.
export default function SiteHeader() {
  const pathname = usePathname() ?? "/";
  const registered = useBreadcrumb();
  const crumbs = registered ?? fallbackCrumbs(pathname);

  return (
    <header className="border-b border-border/70 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-[1180px] items-center gap-2.5 px-5 md:px-8">
        <Link
          href="/"
          className="shrink-0 font-mono text-[12px] font-semibold tracking-[0.18em] text-accent-deep uppercase transition-colors hover:text-foreground"
        >
          Doen
        </Link>

        {crumbs.length > 0 && (
          <nav
            aria-label="Breadcrumb"
            className="flex min-w-0 items-center gap-2 font-mono text-[11px]"
          >
            {crumbs.map((c, i) => {
              const last = i === crumbs.length - 1;
              return (
                <span
                  key={`${c.label}-${i}`}
                  className="flex min-w-0 items-center gap-2"
                >
                  <ChevronRight className="size-3 shrink-0 text-ink-faint" />
                  {c.href && !last ? (
                    <Link
                      href={c.href}
                      className="max-w-[28ch] truncate text-ink-faint transition-colors hover:text-accent-deep"
                    >
                      {c.label}
                    </Link>
                  ) : (
                    <span
                      className="max-w-[34ch] truncate text-foreground"
                      aria-current={last ? "page" : undefined}
                    >
                      {c.label}
                    </span>
                  )}
                </span>
              );
            })}
          </nav>
        )}

        {/* right slot reserved for auth controls (0007) — present in the DOM, empty until then */}
        <div data-slot="auth" className="ml-auto flex shrink-0 items-center" />
      </div>
    </header>
  );
}
