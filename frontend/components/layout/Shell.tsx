'use client';

import { ReactNode, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Users, SlidersHorizontal, Target, Shield, Moon, Sun, Bell, Search, Menu } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { getHealth, headshotUrl } from '@/lib/api';

const NAV = [
  { id: 'players',   href: '/players',   label: 'Players',      Icon: Users },
  { id: 'teams',     href: '/teams',     label: 'Team war room', Icon: Shield },
  { id: 'simulator', href: '/simulator', label: 'Cap simulator', Icon: SlidersHorizontal },
  { id: 'model',     href: '/model',     label: 'Model & backtest', Icon: Target },
];

const TITLES: Record<string, string> = {
  '/players':   'Players',
  '/teams':     'Team war room',
  '/simulator': 'Cap simulator',
  '/model':     'Model & backtest',
};

function Sidebar({ active, collapsed }: { active: string; collapsed: boolean }) {
  return (
    <aside className={`siq-sidebar${collapsed ? ' siq-sidebar--collapsed' : ''}`} style={{
      flexShrink: 0,
      background: 'var(--bg-panel)',
      borderRight: '1px solid var(--border-subtle)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
    }}>
      {/* Logo */}
      <div className="siq-sidebar-logo" style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '0 18px', height: 'var(--topbar-height)',
        borderBottom: '1px solid var(--border-subtle)',
        flexShrink: 0,
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: 8,
          background: 'var(--accent)', display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 13, color: 'var(--text-on-accent)' }}>S</span>
        </div>
        <span className="siq-logo-text" style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 19, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
          Scout<span style={{ color: 'var(--accent)' }}>IQ</span>
        </span>
      </div>

      {/* Nav */}
      <nav className="siq-sidebar-nav" style={{ flex: 1, padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="ds-eyebrow siq-nav-eyebrow" style={{ padding: '8px 8px 6px' }}>Front office</span>
        {NAV.map(({ id, href, label, Icon }) => {
          const isActive = active === id;
          return (
            <Link key={id} href={href} className="siq-sidebar-link" aria-label={label} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '9px 10px', borderRadius: 'var(--radius-md)',
              textDecoration: 'none', position: 'relative',
              fontFamily: 'var(--font-sans)', fontSize: 14,
              fontWeight: isActive ? 600 : 500,
              color: isActive ? 'var(--accent-text)' : 'var(--text-secondary)',
              background: isActive ? 'var(--accent-soft)' : 'transparent',
              transition: 'background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out)',
            }}>
              {isActive && (
                <span style={{
                  position: 'absolute', left: 0, top: 8, bottom: 8,
                  width: 3, borderRadius: 3, background: 'var(--accent)',
                }} />
              )}
              <Icon size={17} />
              <span className="siq-nav-label">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="siq-sidebar-footer" style={{ padding: '12px 14px', borderTop: '1px solid var(--border-subtle)' }}>
        <Badge tone="confidence" variant="outline" size="sm" dot>v0-gbm-conformal</Badge>
      </div>
    </aside>
  );
}

function TopBar({
  title,
  query,
  onQuery,
  sidebarCollapsed,
  onToggleSidebar,
}: {
  title: string;
  query: string;
  onQuery: (q: string) => void;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}) {
  const [dark, setDark] = useState(false);
  const [season, setSeason] = useState<string | null>(null);

  useEffect(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('siq-theme') : null;
    const isDark = saved === 'dark';
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

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute('data-theme', next ? 'dark' : '');
    try { localStorage.setItem('siq-theme', next ? 'dark' : 'light'); } catch {}
  };

  return (
    <header className="siq-topbar" style={{
      height: 'var(--topbar-height)', flexShrink: 0,
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 22px',
      background: 'var(--bg-app)',
      borderBottom: '1px solid var(--border-subtle)',
    }}>
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

      <h1 className="siq-topbar-title" style={{
        fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 20,
        color: 'var(--text-primary)', whiteSpace: 'nowrap', margin: 0,
      }}>
        {title}
      </h1>

      {/* Search */}
      <div className="siq-topbar-search" style={{ flex: 1, maxWidth: 340, marginLeft: 8 }}>
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
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search players…"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--text-primary)',
            }}
          />
          {query && (
            <button onClick={() => onQuery('')} style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-muted)', padding: 0, display: 'flex',
            }}>✕</button>
          )}
        </div>
      </div>

      <div className="siq-topbar-spacer" style={{ flex: 1 }} />

      {season && (
        <span className="siq-season-badge">
          <Badge tone="neutral">{season}</Badge>
        </span>
      )}

      <button onClick={toggleTheme} style={{
        display: 'inline-flex', padding: 7, borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        color: 'var(--text-secondary)', cursor: 'pointer',
      }}>
        {dark ? <Sun size={16} /> : <Moon size={16} />}
      </button>

      <button className="siq-bell-button" style={{
        display: 'inline-flex', padding: 7, borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        color: 'var(--text-secondary)', cursor: 'pointer',
      }}>
        <Bell size={16} />
      </button>
    </header>
  );
}

function PlayerSidebarFigure({ playerId, active }: { playerId: number | null; active: boolean }) {
  if (playerId == null) return null;

  return (
    <img
      src={headshotUrl(playerId)}
      alt=""
      aria-hidden="true"
      className={`siq-sidebar-player-figure${active ? ' siq-sidebar-player-figure--active' : ''}`}
      onError={(e) => { e.currentTarget.style.display = 'none'; }}
    />
  );
}

interface ShellProps {
  children: ReactNode;
}

export function Shell({ children }: ShellProps) {
  const pathname = usePathname();
  const router = useRouter();

  const activeId = NAV.find((n) => pathname.startsWith(n.href))?.id ?? 'players';
  const baseTitle = TITLES[pathname] ?? TITLES[`/${pathname.split('/')[1]}`] ?? 'ScoutIQ';
  const playerProfileMatch = pathname.match(/^\/players\/(\d+)/);
  const profilePlayerId = playerProfileMatch ? Number(playerProfileMatch[1]) : null;

  const [query, setQuery] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const lastSubmittedQuery = useRef('');

  const handleQuery = (q: string) => {
    setQuery(q);
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
    <div className={`siq-shell${sidebarCollapsed ? ' siq-shell--sidebar-collapsed' : ''}`}>
      <Sidebar active={activeId} collapsed={sidebarCollapsed} />
      <PlayerSidebarFigure playerId={profilePlayerId} active={sidebarCollapsed && profilePlayerId != null} />
      <div className="siq-shell-workspace" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <TopBar
          title={baseTitle}
          query={query}
          onQuery={handleQuery}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((collapsed) => !collapsed)}
        />
        <main className="siq-main">
          <div className="siq-content">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
