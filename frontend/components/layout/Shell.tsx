'use client';

import { ReactNode, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Users, SlidersHorizontal, Target, Shield, Handshake, CalendarRange, ArrowLeftRight, Moon, Sun, Search, Menu, X } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { getHealth } from '@/lib/api';

const NAV = [
  { id: 'players', href: '/players', label: 'Players', mobileLabel: 'Players', Icon: Users },
  { id: 'teams', href: '/teams', label: 'Team war room', mobileLabel: 'Teams', Icon: Shield },
  { id: 'free-agency', href: '/free-agency', label: 'Free agency', mobileLabel: 'Market', Icon: Handshake },
  { id: 'offseason', href: '/offseason', label: 'Offseason plan', mobileLabel: 'Plan', Icon: CalendarRange },
  { id: 'trade-lab', href: '/trade-lab', label: 'Trade lab', mobileLabel: 'Trade', Icon: ArrowLeftRight },
  { id: 'simulator', href: '/simulator', label: 'Cap simulator', mobileLabel: 'Cap sim', Icon: SlidersHorizontal },
  { id: 'model', href: '/model', label: 'Model trust', mobileLabel: 'Trust', Icon: Target },
];

const TITLES: Record<string, string> = {
  '/':          'Front office',
  '/players':   'Players',
  '/teams':     'Team war room',
  '/free-agency': 'Free agency',
  '/offseason': 'Offseason plan',
  '/trade-lab': 'Trade lab',
  '/simulator': 'Cap simulator',
  '/model':     'Model trust',
};

function Sidebar({ active, collapsed }: { active: string; collapsed: boolean }) {
  return (
    <aside id="primary-sidebar" className={`siq-sidebar${collapsed ? ' siq-sidebar--collapsed' : ''}`}>
      <Link href="/" className="siq-sidebar-logo" aria-label="ScoutIQ home">
        <div className="siq-brand-mark">
          <span>S</span>
        </div>
        <span className="siq-logo-text">
          Scout<span>IQ</span>
        </span>
      </Link>

      <nav className="siq-sidebar-nav" aria-label="Primary navigation">
        <span className="siq-nav-eyebrow">Front office</span>
        {NAV.map(({ id, href, label, Icon }) => {
          const isActive = active === id;
          return (
            <Link
              key={id}
              href={href}
              className={`siq-sidebar-link${isActive ? ' siq-sidebar-link--active' : ''}`}
              aria-label={label}
              aria-current={isActive ? 'page' : undefined}
              title={collapsed ? label : undefined}
            >
              <Icon size={17} />
              <span className="siq-nav-label">{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="siq-sidebar-footer">
        <span className="siq-sidebar-footer-label">Valuation model</span>
        <Badge tone="confidence" variant="outline" size="sm" dot>v1 · adaptive intervals</Badge>
      </div>
    </aside>
  );
}

function MobileNav({ active }: { active: string }) {
  return (
    <nav className="siq-mobile-nav" aria-label="Primary navigation">
      {NAV.map(({ id, href, label, mobileLabel, Icon }) => {
        const isActive = active === id;
        return (
          <Link
            key={id}
            href={href}
            className={`siq-mobile-nav__link${isActive ? ' siq-mobile-nav__link--active' : ''}`}
            aria-label={label}
            aria-current={isActive ? 'page' : undefined}
          >
            <Icon size={17} />
            <span>{mobileLabel}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function TopBar({
  title,
  sidebarCollapsed,
  onToggleSidebar,
}: {
  title: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [dark, setDark] = useState(false);
  const [season, setSeason] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const lastSubmittedQuery = useRef('');

  useEffect(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('siq-theme') : null;
    const isDark = saved !== 'light';
    setDark(isDark);
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : '');
  }, []);

  // Season label is sourced from the backend (LATEST_SEASON) so it tracks the
  // loaded data instead of being hardcoded here.
  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((h) => setSeason(h.current_season))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const toggleTheme = (e: ReactMouseEvent<HTMLButtonElement>) => {
    const next = !dark;
    const apply = () => {
      setDark(next);
      document.documentElement.setAttribute('data-theme', next ? 'dark' : '');
      try { localStorage.setItem('siq-theme', next ? 'dark' : 'light'); } catch {}
    };

    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!doc.startViewTransition || reduceMotion) {
      apply();
      return;
    }

    const rect = e.currentTarget.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const radius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    );

    doc.startViewTransition(apply).ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 480, easing: 'cubic-bezier(0.16,1,0.3,1)', pseudoElement: '::view-transition-new(root)' },
      );
    }).catch(() => {});
  };

  useEffect(() => {
    const trimmed = query.trim();
    const t = setTimeout(() => {
      if (trimmed) {
        if (trimmed !== lastSubmittedQuery.current) {
          lastSubmittedQuery.current = trimmed;
          router.replace(`/players?q=${encodeURIComponent(trimmed)}`);
        }
      } else if (lastSubmittedQuery.current && pathname.startsWith('/players')) {
        lastSubmittedQuery.current = '';
        router.replace('/players');
      }
    }, 250);
    return () => clearTimeout(t);
  }, [pathname, query, router]);

  return (
    <header className={`siq-topbar${pathname.startsWith('/simulator') ? ' siq-topbar--compact' : ''}`}>
      <button
        type="button"
        className="siq-icon-button siq-sidebar-toggle"
        onClick={onToggleSidebar}
        aria-label={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
        aria-expanded={!sidebarCollapsed}
        aria-controls="primary-sidebar"
        title={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
      >
        <Menu size={17} />
      </button>

      <div className="siq-topbar-title">
        {title}
      </div>

      {/* Search — hidden on the simulator, which owns its own player picker
          (avoids two competing search bars on that page). */}
      {!pathname.startsWith('/simulator') && !pathname.startsWith('/trade-lab') && (
      <div className="siq-topbar-search">
        <div className="siq-search-field">
          <Search size={16} aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search players…"
            aria-label="Search players"
          />
          {query && (
            <button
              type="button"
              className="siq-search-clear"
              onClick={() => setQuery('')}
              aria-label="Clear player search"
              title="Clear player search"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>
      )}

      <div className="siq-topbar-spacer" />

      {season && (
        <span className="siq-season-badge">
          <Badge tone="neutral">{season}</Badge>
        </span>
      )}

      <div className="siq-topbar-actions">
        <button
          type="button"
          className="siq-icon-button"
          onClick={toggleTheme}
          aria-label={dark ? 'Use light theme' : 'Use dark theme'}
          title={dark ? 'Use light theme' : 'Use dark theme'}
        >
          {dark ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>
    </header>
  );
}

interface ShellProps {
  children: ReactNode;
}

export function Shell({ children }: ShellProps) {
  const pathname = usePathname();

  const activeId = NAV.find((n) => pathname.startsWith(n.href))?.id ?? '';
  const baseTitle = TITLES[pathname] ?? TITLES[`/${pathname.split('/')[1]}`] ?? 'ScoutIQ';

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <>
      <a className="siq-skip-link" href="#main-content">Skip to content</a>
      <div className={`siq-shell${sidebarCollapsed ? ' siq-shell--sidebar-collapsed' : ''}`}>
        <Sidebar active={activeId} collapsed={sidebarCollapsed} />
        <div className="siq-shell-workspace">
          <TopBar
            title={baseTitle}
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((collapsed) => !collapsed)}
          />
          <main id="main-content" className="siq-main" tabIndex={-1}>
            <div key={pathname} className="siq-content">
              {children}
            </div>
          </main>
        </div>
        <MobileNav active={activeId} />
      </div>
    </>
  );
}
