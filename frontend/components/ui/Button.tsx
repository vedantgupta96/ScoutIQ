import { ButtonHTMLAttributes, ReactNode } from 'react';
import Link from 'next/link';

type Variant = 'primary' | 'secondary' | 'ghost';
type Size = 'sm' | 'md';

const VARIANT_CLASS: Record<Variant, string> = {
  primary: 'siq-primary-button',
  secondary: 'siq-secondary-button',
  ghost: 'siq-ghost-button',
};

function buttonClass(variant: Variant, size: Size, className?: string): string {
  return [VARIANT_CLASS[variant], size === 'sm' ? 'siq-button--sm' : '', className ?? '']
    .filter(Boolean)
    .join(' ');
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}

export function Button({ variant = 'secondary', size = 'md', icon, className, children, type = 'button', ...rest }: ButtonProps) {
  return (
    <button type={type} className={buttonClass(variant, size, className)} {...rest}>
      {icon}
      {children}
    </button>
  );
}

interface ButtonLinkProps {
  href: string;
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}

/** A next/link styled as a button — for navigations that read as actions. */
export function ButtonLink({ href, variant = 'secondary', size = 'md', icon, className, children }: ButtonLinkProps) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {icon}
      {children}
    </Link>
  );
}
