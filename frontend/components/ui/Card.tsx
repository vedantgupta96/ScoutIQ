import { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  eyebrow?: string;
  icon?: ReactNode;
  action?: ReactNode;
  padded?: boolean;
  flushBody?: boolean;
  className?: string;
  headingLevel?: 'h2' | 'h3';
}

export function Card({ children, eyebrow, icon, action, padded, flushBody, className = '', headingLevel = 'h2' }: CardProps) {
  const Heading = headingLevel;
  return (
    <div className={`siq-card ${className}`.trim()}>
      {eyebrow && (
        <div className="siq-card__head">
          <div className="siq-card__head-main">
            {icon && <span className="siq-card__icon">{icon}</span>}
            <Heading className="ds-eyebrow">{eyebrow}</Heading>
          </div>
          {action && <div className="siq-card__action">{action}</div>}
        </div>
      )}
      <div className={`siq-card__body${flushBody ? ' siq-card__body--flush' : padded ? ' siq-card__body--padded' : ''}`}>
        {children}
      </div>
    </div>
  );
}
