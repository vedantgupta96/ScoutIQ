import { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}

/** Centered no-data block: says what's missing and, when possible, what to do about it. */
export function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div className="siq-empty">
      {icon && <span className="siq-empty__icon">{icon}</span>}
      <span className="siq-empty__title">{title}</span>
      {description && <p className="siq-empty__desc">{description}</p>}
      {action && <div className="siq-empty__action">{action}</div>}
    </div>
  );
}
