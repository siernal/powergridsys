// RiskBadge.tsx — цветной бейдж уровня риска с опциональным процентом.
// Используется в таблицах объектов и карточке актива.
// CSS-классы risk-low / risk-medium / risk-high определены в styles.css.

interface Props {
  level?: string | null;        // «low» / «medium» / «high»
  probability?: number | null;  // вероятность 0..1 (отображается как %)
}

export default function RiskBadge({ level, probability }: Props) {
  // Если уровень не задан — показываем нейтральный прочерк
  if (!level) return <span className="badge badge--neutral">—</span>;

  const labels: Record<string, string> = {
    low: "Низкий", medium: "Средний", high: "Высокий",
  };

  return (
    <span className={`badge risk-${level}`}>
      {labels[level] || level}
      {/* Показываем процент только если передан */}
      {typeof probability === "number" ? ` · ${(probability * 100).toFixed(1)}%` : ""}
    </span>
  );
}
