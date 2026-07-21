import { ReactNode, useLayoutEffect, useRef, useState } from 'react';

interface SegmentedControlProps<T extends string> {
  options: ReadonlyArray<{ value: T; label: string; icon?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}

/** A boxed group of mutually exclusive filter options (pressed-button semantics).
 *  A single indicator slides under the active option instead of each option
 *  swapping its own background, so switching reads as one continuous motion. */
export function SegmentedControl<T extends string>({ options, value, onChange, ariaLabel }: SegmentedControlProps<T>) {
  const groupRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);

  // Measure the active option and place the indicator over it. Runs before paint on
  // value/options change, and on resize, so the pill tracks variable-width segments.
  useLayoutEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    const measure = () => {
      const active = group.querySelector<HTMLElement>('[data-active="true"]');
      if (!active) return;
      setIndicator({ left: active.offsetLeft, width: active.offsetWidth });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(group);
    return () => observer.disconnect();
  }, [value, options]);

  return (
    <div className="siq-segmented" role="group" aria-label={ariaLabel} ref={groupRef}>
      {indicator && (
        <span
          className="siq-segmented__indicator"
          aria-hidden="true"
          style={{ transform: `translateX(${indicator.left}px)`, width: indicator.width }}
        />
      )}
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          data-active={option.value === value}
          className={`siq-segmented__option${option.value === value ? ' siq-segmented__option--active' : ''}`}
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}
