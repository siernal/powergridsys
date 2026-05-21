// Loading.tsx — компоненты индикаторов загрузки.
// Spinner — маленький инлайн-спиннер (используется внутри кнопок при ожидании).
// Loading  — полноэкранный блок с текстом (используется пока загружается страница).

/** Маленький анимированный спиннер для кнопок в состоянии «ожидание» */
export function Spinner() {
  return <span className="spinner" aria-label="Загрузка" />;
}

/** Блок загрузки на весь контентный блок (показывается до получения данных) */
export function Loading({ text = "Загрузка..." }: { text?: string }) {
  return (
    <div className="row" style={{ padding: 24 }}>
      <Spinner /> <span className="muted">{text}</span>
    </div>
  );
}
