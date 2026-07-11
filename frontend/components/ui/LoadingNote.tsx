import { ReactNode } from 'react';

/** Quiet centered loading text with a polite live region so the wait is announced. */
export function LoadingNote({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div role="status" className={`siq-loading-note ${className}`.trim()}>
      {children}
    </div>
  );
}
