'use client';

import { ReactNode, useRef, type KeyboardEvent } from 'react';

interface TabsProps<T extends string> {
  tabs: ReadonlyArray<{ key: T; label: string; icon?: ReactNode }>;
  active: T;
  onChange: (key: T) => void;
  ariaLabel: string;
  /** Tab ids become `${idPrefix}-tab-${key}`; point the panel's aria-labelledby at the active one. */
  idPrefix: string;
  /** id of the tabpanel this tablist controls. */
  panelId: string;
  className?: string;
}

/** Roving-tabindex tablist: ArrowLeft/ArrowRight/Home/End move selection and focus. */
export function Tabs<T extends string>({ tabs, active, onChange, ariaLabel, idPrefix, panelId, className }: TabsProps<T>) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex = index;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = tabs.length - 1;
    else return;

    event.preventDefault();
    onChange(tabs[nextIndex].key);
    tabRefs.current[nextIndex]?.focus();
  };

  return (
    <div className={className} role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab, index) => (
        <button
          key={tab.key}
          id={`${idPrefix}-tab-${tab.key}`}
          ref={(el) => { tabRefs.current[index] = el; }}
          type="button"
          role="tab"
          aria-selected={active === tab.key}
          aria-controls={panelId}
          tabIndex={active === tab.key ? 0 : -1}
          onClick={() => onChange(tab.key)}
          onKeyDown={(event) => onKeyDown(event, index)}
          className={active === tab.key ? 'is-active' : undefined}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}
