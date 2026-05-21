// Modal.tsx — универсальная модальная оболочка.
// Контент передаётся через children; закрывается кликом по фону, по крестику или Esc.
// При открытом окне блокируется прокрутка body, чтобы фон не уезжал.

import { ReactNode, useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  width?: number;       // максимальная ширина в px
}

export default function Modal({ open, title, onClose, children, width = 560 }: Props) {
  // Закрытие по клавише Escape + блокировка прокрутки фона
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        style={{ maxWidth: width }}
        onClick={(e) => e.stopPropagation()}   // клик внутри окна не закрывает
      >
        <div className="modal__header">
          <div className="modal__title">{title}</div>
          <button className="modal__close" onClick={onClose} aria-label="Закрыть">×</button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  );
}
