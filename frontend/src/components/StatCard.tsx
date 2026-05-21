// StatCard.tsx — карточка с одним числовым показателем (KPI-блок).
// Используется на дашборде и в карточке объекта для отображения ключевых метрик.
// accent задаёт цвет значения: success=зелёный, warning=оранжевый, danger=красный.

interface Props {
  label: string;                                        // подпись метрики
  value: string | number | null | undefined;            // числовое или строковое значение
  hint?: string;                                        // мелкий поясняющий текст под значением
  accent?: "default" | "warning" | "danger" | "success";
}

// Соответствие accent → цвет текста (CSS-цвет напрямую, без Tailwind)
const accentColor = {
  default: "#1f2937",
  warning: "#b45309",
  danger:  "#991b1b",
  success: "#15803d",
};

export default function StatCard({ label, value, hint, accent = "default" }: Props) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value" style={{ color: accentColor[accent] }}>
        {/* ?? "—" — если значение null/undefined, показываем прочерк */}
        {value ?? "—"}
      </div>
      {hint && <div className="stat__hint">{hint}</div>}
    </div>
  );
}
