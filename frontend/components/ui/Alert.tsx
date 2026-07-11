import { ReactNode } from 'react';

type Tone = 'neutral' | 'negative' | 'warning' | 'info' | 'confidence';

interface AlertProps {
  children: ReactNode;
  tone?: Tone;
  title?: string;
  icon?: ReactNode;
  className?: string;
}

/** Inline status note: errors, caveats, calibration remarks. Quiet tinted panel, no chrome. */
export function Alert({ children, tone = 'neutral', title, icon, className = '' }: AlertProps) {
  return (
    <div className={`siq-alert siq-alert--${tone} ${className}`.trim()} role={tone === 'negative' ? 'alert' : undefined}>
      {icon && <span className="siq-alert__icon">{icon}</span>}
      <div className="siq-alert__body">
        {title && <span className="siq-alert__title">{title}</span>}
        <div className="siq-alert__text">{children}</div>
      </div>
    </div>
  );
}
