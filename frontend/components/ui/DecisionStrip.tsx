import type { ReactNode } from 'react';

export type DecisionStripTone = 'neutral' | 'positive' | 'negative' | 'warning' | 'confidence';

export interface DecisionStripItem {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: DecisionStripTone;
}

export function DecisionStrip({
  lead,
  items,
  actions,
  ariaLabel = 'Decision status',
}: {
  lead: DecisionStripItem;
  items: DecisionStripItem[];
  actions?: ReactNode;
  ariaLabel?: string;
}) {
  const renderItem = (item: DecisionStripItem, leadItem = false) => (
    <div
      key={item.label}
      className={`siq-decision-strip__item${leadItem ? ' siq-decision-strip__item--lead' : ''}`}
      data-tone={item.tone ?? 'neutral'}
    >
      <span className="siq-decision-strip__label">{item.label}</span>
      <strong className="siq-decision-strip__value ds-tnum">{item.value}</strong>
      {item.detail != null ? <span className="siq-decision-strip__detail">{item.detail}</span> : null}
    </div>
  );

  return (
    <section className="siq-decision-strip" aria-label={ariaLabel}>
      {renderItem(lead, true)}
      <div className="siq-decision-strip__support">
        {items.map((item) => renderItem(item))}
      </div>
      {actions ? <div className="siq-decision-strip__actions">{actions}</div> : null}
    </section>
  );
}
