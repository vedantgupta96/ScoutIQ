'use client';

import { ReactNode, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Users, SlidersHorizontal, Target, Moon, Sun, Bell, Search } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';

const NAV = [
  { id: 'players',   href: '/players',   label: 'Players',      Icon: Users },
  { id: 'simulator', href: '/simulator', label: 'Cap simulator', Icon: SlidersHorizontal },
  { id: 'model',     href: '/model',     label: 'Model & backtest', Icon: Target },
];

const TITLES: Record<string, string> = {
  '/players':   'Players',
  '/simulator': 'Cap simulator',
  '/model':     'Model & backtest',
};

function Sidebar({ active }: { active: string }) {
  return (
    <aside style={{
      width: 'var(--sidebar-width)',
      flexShrink: 0,
      background: 'var(--bg-panel)',
      borderRight: '1px solid var(--border-subtle)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
    }}>
      {/* Logo */}
      <div style={{
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
          <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 13, color: '#fff' }}>S</span>
        </div>
        <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 19, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
          Scout<span style={{ color: 'var(--accent)' }}>IQ</span>
        </span>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="ds-eyebrow" style={{ padding: '8px 8px 6px' }}>Front office</span>
        {NAV.map(({ id, href, label, Icon }) => {
          const isActive = active === id;
          return (
            <Link key={id} href={href} style={{
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
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border-subtle)' }}>
        <Badge tone="confidence" variant="outline" size="sm" dot>v0-gbm-conformal</Badge>
      </div>
    </aside>
  );
}

function TopBar({ title, query, onQuery }: { title: string; query: string; onQuery: (q: string) => void }) {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('siq-theme') : null;
    const isDark = saved === 'dark';
    setDark(isDark);
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : '');
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute('data-theme', next ? 'dark' : '');
    try { localStorage.setItem('siq-theme', next ? 'dark' : 'light'); } catch {}
  };

  return (
    <header style={{
      height: 'var(--topbar-height)', flexShrink: 0,
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 22px',
      background: 'var(--bg-app)',
      borderBottom: '1px solid var(--border-subtle)',
    }}>
      <h1 style={{
        fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 20,
        color: 'var(--text-primary)', whiteSpace: 'nowrap', margin: 0,
      }}>
        {title}
      </h1>

      {/* Search */}
      <div style={{ flex: 1, maxWidth: 340, marginLeft: 8 }}>
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

      <div style={{ flex: 1 }} />

      <Badge tone="neutral">2024-25</Badge>

      <button onClick={toggleTheme} style={{
        display: 'inline-flex', padding: 7, borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        color: 'var(--text-secondary)', cursor: 'pointer',
      }}>
        {dark ? <Sun size={16} /> : <Moon size={16} />}
      </button>

      <button style={{
        display: 'inline-flex', padding: 7, borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        color: 'var(--text-secondary)', cursor: 'pointer',
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
  const router = useRouter();

  const activeId = NAV.find((n) => pathname.startsWith(n.href))?.id ?? 'players';
  const baseTitle = TITLES[pathname] ?? TITLES[`/${pathname.split('/')[1]}`] ?? 'ScoutIQ';

  const [query, setQuery] = useState('');

  const handleQuery = (q: string) => {
    setQuery(q);
    if (q.trim()) {
      router.push(`/players?q=${encodeURIComponent(q.trim())}`);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar active={activeId} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <TopBar title={baseTitle} query={query} onQuery={handleQuery} />
        <main style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          <div style={{ maxWidth: 1440, margin: '0 auto' }}>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
