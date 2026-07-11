import { ReactNode } from 'react';

interface FieldProps {
  label: string;
  htmlFor?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  /** Lay the label to the left of the control (toolbar style) instead of above it. */
  inline?: boolean;
}

/** Labeled form control: eyebrow label above the control, optional hint below. */
export function Field({ label, htmlFor, hint, children, className = '', inline = false }: FieldProps) {
  return (
    <div className={`siq-field${inline ? ' siq-field--inline' : ''} ${className}`.trim()}>
      <label className="siq-field__label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <span className="siq-field__hint">{hint}</span>}
    </div>
  );
}
