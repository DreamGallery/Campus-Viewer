import { useEffect, useId, useRef, type ReactNode } from 'react';
import './confirm-dialog.css';

export function ConfirmDialog({ title, children, confirmLabel, cancelLabel = '取消', onConfirm, onCancel }: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    cancelButton.current?.focus({ preventScroll: true });
    return () => { element?.close(); };
  }, []);

  return <dialog ref={dialog} className="work-confirm-dialog" role="alertdialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-message`}
    onCancel={event => { event.preventDefault(); onCancel(); }}
    onClick={event => {
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onCancel();
    }}>
    <h2 id={`${id}-title`} className="work-confirm-heading">{title}</h2>
    <div id={`${id}-message`} className="work-confirm-message">{children}</div>
    <div className="work-confirm-actions">
      <button ref={cancelButton} type="button" className="work-confirm-button" autoFocus onClick={onCancel}>{cancelLabel}</button>
      <button type="button" className="work-confirm-button work-confirm-primary" onClick={onConfirm}>{confirmLabel}</button>
    </div>
  </dialog>;
}
