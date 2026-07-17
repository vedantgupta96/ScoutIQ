'use client';

import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from 'react';
import { X } from 'lucide-react';

interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

export function Dialog({ open, title, onClose, children, footer }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || !open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
      const previousFocus = previousFocusRef.current;
      requestAnimationFrame(() => {
        // The connection check avoids stealing focus during React Strict Mode's
        // development-only effect replay, while restoring it after a real close.
        if (!dialog.isConnected || !dialog.open) previousFocus?.focus();
      });
    };
  }, [open]);

  if (!open) return null;

  const closeOnBackdrop = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  return (
    <dialog
      ref={ref}
      className="siq-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={closeOnBackdrop}
    >
      <div className="siq-dialog__surface">
        <header className="siq-dialog__header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="siq-dialog__close" onClick={onClose} aria-label="Close dialog">
            <X size={19} />
          </button>
        </header>
        <div className="siq-dialog__body">{children}</div>
        {footer ? <footer className="siq-dialog__footer">{footer}</footer> : null}
      </div>
    </dialog>
  );
}
