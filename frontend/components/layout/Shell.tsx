'use client';

import { ReactNode, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Users, SlidersHorizontal, Target, Shield, Handshake, CalendarRange, Moon, Sun, Bell, Search, Menu } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { getHealth } from '@/lib/api';

const NAV = [
  { id: 'players',   href: '/players',   label: 'Players',      Icon: Users },
  { id: 'teams',     href: '/teams',     label: 'Team war room', Icon: Shield },
  { id: 'free-agency', href: '/free-agency', label: 'Free agency', Icon: Handshake },
  { id: 'offseason', href: '/offseason', label: 'Offseason plan', Icon: CalendarRange },
  { id: 'simulator', href: '/simulator', label: 'Cap simulator', Icon: SlidersHorizontal },
  { id: 'model',     href: '/model',     label: 'Model & backtest', Icon: Target },
];

const TITLES: Record<string, string> = {
  '/players':   'Players',
  '/teams':     'Team war room',
  '/free-agency': 'Free agency',
  '/offseason': 'Offseason plan',
  '/simulator': 'Cap simulator',
  '/model':     'Model & backtest',
};

function Sidebar({ active, collapsed }: { active: string; collapsed: boolean }) {
  return (
    <aside className={`siq-sidebar${collapsed ? ' siq-sidebar--collapsed' : ''}`}>
      {/* Logo */}
      <div className="siq-sidebar-logo">
        <div className="siq-brand-mark">
          <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 13, color: 'var(--text-on-accent)' }}>S</span>
        </div>
        <span className="siq-logo-text" style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 19, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
          Scout<span style={{ color: 'var(--accent)' }}>IQ</span>
        </span>
      </div>

      {/* Nav */}
      <nav className="siq-sidebar-nav" style={{ flex: 1, padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="ds-eyebrow siq-nav-eyebrow siq-enter-x" style={{ padding: '8px 8px 6px', ['--i' as string]: 0 }}>Front office</span>
        {NAV.map(({ id, href, label, Icon }, i) => {
          const isActive = active === id;
          return (
            <Link key={id} href={href} className="siq-sidebar-link siq-enter-x" aria-label={label} style={{
              ['--i' as string]: i + 1,
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '9px 10px', borderRadius: 'var(--radius-md)',
              textDecoration: 'none', position: 'relative',
              fontFamily: 'var(--font-sans)', fontSize: 14,
              fontWeight: isActive ? 700 : 500,
              color: isActive ? 'var(--accent-text)' : 'var(--text-secondary)',
              background: isActive ? 'var(--nav-active-bg)' : 'transparent',
              transition: 'background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out)',
            }}>
              {isActive && (
                <span style={{
                  position: 'absolute', left: 7, right: 7, bottom: 4,
                  height: 1, borderRadius: 3, background: 'var(--accent)',
                }} />
              )}
              <Icon size={17} />
              <span className="siq-nav-label">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer — a quiet half-court etched into the dead space above the
          model-version badge: structure the data sits on, not décor. */}
      <div className="siq-sidebar-footer">
        <svg className="siq-sidebar-court" viewBox="0 0 200 122" aria-hidden="true">
          <g fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 121 H198" />
            <rect x="68" y="45" width="64" height="76" />
            <circle cx="100" cy="45" r="24" />
            <path d="M86 96 H114" />
            <circle cx="100" cy="103" r="4.5" />
            <path d="M14 121 V68 A108 108 0 0 1 186 68 V121" />
          </g>
        </svg>
        <Badge tone="confidence" variant="outline" size="sm" dot>v0-gbm-conformal</Badge>
      </div>
    </aside>
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

  // Arena lights: the new theme sweeps across the floor as a circle expanding
  // from the toggle (View Transitions). The DOM attribute flip inside the
  // callback is synchronous, so the snapshot pair is always consistent; without
  // browser support or with reduced motion it falls back to an instant switch.
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
        { duration: 520, easing: 'cubic-bezier(0.22,1,0.36,1)', pseudoElement: '::view-transition-new(root)' },
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
    <header className="siq-topbar">
      <button
        type="button"
        className="siq-icon-button"
        onClick={onToggleSidebar}
        aria-label={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
        aria-pressed={sidebarCollapsed}
        title={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
      >
        <Menu size={17} />
      </button>

      <div className="siq-topbar-title siq-enter" style={{
        ['--i' as string]: 1,
        fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 20,
        color: 'var(--text-primary)', whiteSpace: 'nowrap', margin: 0,
      }}>
        {title}
      </div>

      {/* Search — hidden on the simulator, which owns its own player picker
          (avoids two competing search bars on that page). */}
      {!pathname.startsWith('/simulator') && (
      <div className="siq-topbar-search siq-enter" style={{ ['--i' as string]: 2, flex: 1, maxWidth: 340, marginLeft: 8 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 10px',
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
        }}>
          <Search size={15} color="var(--text-muted)" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search players…"
            aria-label="Search players"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--text-primary)',
            }}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear player search"
              title="Clear player search"
              style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-muted)', padding: 0, display: 'flex',
            }}>✕</button>
          )}
        </div>
      </div>
      )}

      <div className="siq-topbar-spacer" style={{ flex: 1 }} />

      {season && (
        <span className="siq-season-badge">
          <Badge tone="neutral">{season}</Badge>
        </span>
      )}

      <button
        type="button"
        className="siq-icon-button"
        onClick={toggleTheme}
        aria-label={dark ? 'Use light theme' : 'Use dark theme'}
        title={dark ? 'Use light theme' : 'Use dark theme'}
        style={{
        display: 'inline-flex', padding: 7, borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        color: 'var(--text-secondary)', cursor: 'pointer',
      }}>
        {dark ? <Sun size={16} /> : <Moon size={16} />}
      </button>

      <button
        type="button"
        className="siq-icon-button siq-bell-button"
        aria-label="Notifications are not available yet"
        title="Notifications are not available yet"
        disabled
        style={{
        display: 'inline-flex', padding: 7, borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        color: 'var(--text-muted)', cursor: 'not-allowed', opacity: 0.62,
      }}>
        <Bell size={16} />
      </button>
    </header>
  );
}

interface ShellProps {
  children: ReactNode;
}

export function Shell({ children }: ShellProps) {
  const pathname = usePathname();

  const activeId = NAV.find((n) => pathname.startsWith(n.href))?.id ?? 'players';
  const baseTitle = TITLES[pathname] ?? TITLES[`/${pathname.split('/')[1]}`] ?? 'ScoutIQ';

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className={`siq-shell${sidebarCollapsed ? ' siq-shell--sidebar-collapsed' : ''}`}>
      <Sidebar active={activeId} collapsed={sidebarCollapsed} />
      <div className="siq-shell-workspace" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <TopBar
          title={baseTitle}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((collapsed) => !collapsed)}
        />
        <main className="siq-main">
          <div key={pathname} className="siq-content siq-route-enter">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
