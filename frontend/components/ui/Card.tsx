import { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  eyebrow?: string;
  icon?: ReactNode;
  action?: ReactNode;
  padded?: boolean;
  flushBody?: boolean;
  className?: string;
}

export function Card({ children, eyebrow, icon, action, padded, flushBody, className = '' }: CardProps) {
  return (
    <div className={`siq-card ${className}`.trim()}>
      {eyebrow && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px 0', gap: 8,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            {icon && <span style={{ color: 'var(--text-muted)', display: 'flex' }}>{icon}</span>}
            <span className="ds-eyebrow">{eyebrow}</span>
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      <div style={{ padding: flushBody ? 0 : padded ? 16 : '12px 16px 16px' }}>
        {children}
      </div>
    </div>
  );
}
