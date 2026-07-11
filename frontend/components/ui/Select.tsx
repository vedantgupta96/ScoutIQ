import { SelectHTMLAttributes } from 'react';

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  size?: never; // native size attr clashes with the visual scale; use selectSize
  selectSize?: 'sm' | 'md';
}

/** The one styled native select. Pass aria-label when there is no visible label. */
export function Select({ selectSize = 'md', className, children, ...rest }: SelectProps) {
  return (
    <select
      className={`siq-select${selectSize === 'sm' ? ' siq-select--sm' : ''} ${className ?? ''}`.trim()}
      {...rest}
    >
      {children}
    </select>
  );
}
