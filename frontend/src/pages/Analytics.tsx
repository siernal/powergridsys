// Analytics.tsx — сводная аналитическая страница сети.
// Отображает: линейный тренд отказов по месяцам, круговую диаграмму распределения рисков,
// гистограмму тяжести отказов, гистограмму структуры парка по статусам,
// а также таблицу последних 20 отказов с фильтрацией по тяжести.
// Все данные загружаются параллельно через Promise.all при монтировании.

import { useEffect, useState } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
  PieChart, Pie, Cell,
} from "recharts";
import {
  getFailuresByMonth, getRiskDistribution,
  getAnalyticsSummary, listFailures,
} from "../api/client";
import type { AnalyticsSummary, Failure } from "../types";
import { Loading } from "../components/Loading";

// Цвета для диаграмм: low=зелёный, medium=жёлтый, high=красный — соответствуют уровням риска
const COLORS = ["#16a34a", "#f59e0b", "#dc2626"];

// Человекочитаемые метки тяжести отказов (ключи — значения Failure.severity из БД)
const SEVERITY_LABEL: Record<string, string> = {
  minor: "Незначительный", major: "Серьёзный", critical: "Критический",
};

export default function AnalyticsPage() {
  // Сводные KPI сети (количество объектов, отказов, ремонтов за год и т.д.)
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  // Отказы по месяцам — данные для линейного графика тренда
  const [byMonth, setByMonth] = useState<{ month: string; count: number }[]>([]);
  // Распределение объектов по уровням риска {low: N, medium: M, high: K}
  const [riskDist, setRiskDist] = useState<Record<string, number>>({});
  // Полный список отказов для таблицы и вычисления MTTR
  const [failures, setFailures] = useState<Failure[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Один параллельный запрос при первом рендере
  useEffect(() => {
    Promise.all([
      getAnalyticsSummary(), getFailuresByMonth(),
      getRiskDistribution(), listFailures(),
    ])
      .then(([s, m, r, f]) => {
        setSummary(s); setByMonth(m); setRiskDist(r); setFailures(f);
      })
      .catch((e) => setErr(e?.message || "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading />;
  if (err) return <div className="error">{err}</div>;

  // Подсчёт отказов по тяжести для гистограммы — агрегируем на клиенте
  const sevCount: Record<string, number> = {};
  failures.forEach((f) => { sevCount[f.severity] = (sevCount[f.severity] || 0) + 1; });
  const sevData = [
    { name: "Минор",   value: sevCount.minor || 0,    fill: "#16a34a" },
    { name: "Серьёзн.", value: sevCount.major || 0,   fill: "#f59e0b" },
    { name: "Критич.", value: sevCount.critical || 0, fill: "#dc2626" },
  ];

  // Преобразуем словарь рисков в массив для recharts
  const riskData = Object.entries(riskDist).map(([level, count]) => ({
    name: level, value: count, level,
  }));

  // Средний простой (MTTR — Mean Time To Repair) только для завершённых отказов
  const completed = failures.filter((f) => f.resolved_at);
  const avgDowntime = completed.length
    ? completed.reduce((s, f) => s + (f.downtime_hours || 0), 0) / completed.length
    : 0;

  return (
    <div>
      <h1>Аналитика</h1>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Сводные показатели работы сети, тренды отказов и эффективности обслуживания.
      </p>

      {/* ── KPI-карточки ─────────────────────────────────────────── */}
      <div className="stat-grid">
        <div className="stat">
          <div className="stat__label">Объектов</div>
          <div className="stat__value">{summary?.total_assets}</div>
        </div>
        <div className="stat">
          <div className="stat__label">Отказов / год</div>
          <div className="stat__value">{summary?.total_failures_last_year}</div>
        </div>
        <div className="stat">
          <div className="stat__label">Ремонтов / год</div>
          <div className="stat__value">{summary?.total_repairs_last_year}</div>
        </div>
        {/* Средний простой (MTTR) — считается только по отказам с известной датой восстановления */}
        <div className="stat">
          <div className="stat__label">Средн. простой, ч</div>
          <div className="stat__value">{avgDowntime.toFixed(1)}</div>
        </div>
        {/* Средний health-score по всем объектам из цифровой копии */}
        <div className="stat">
          <div className="stat__label">Средн. состояние</div>
          <div className="stat__value">{summary?.avg_health_score?.toFixed(1) ?? "—"}</div>
        </div>
      </div>

      {/* ── Четыре диаграммы в сетке 2×2 ────────────────────────── */}
      <div className="grid-2">
        {/* Линейный тренд отказов по месяцам за последний год */}
        <div className="card">
          <div className="card__title">Отказы по месяцам</div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={byMonth}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="month" fontSize={12} />
              <YAxis fontSize={12} allowDecimals={false} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="count" stroke="#2563eb" strokeWidth={2}
                    name="Отказов" dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Круговая диаграмма распределения объектов по уровням риска */}
        <div className="card">
          <div className="card__title">Распределение по уровню риска</div>
          {riskData.length === 0 ? (
            <div className="empty">Сначала рассчитайте риски в разделе «Прогноз отказов».</div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={riskData} dataKey="value" nameKey="name"
                     outerRadius={100} label>
                  {/* Цвета назначаются по порядку: low→зел, medium→жёлт, high→красн */}
                  {riskData.map((_, i) => <Cell key={i} fill={COLORS[i % 3]} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Гистограмма тяжести отказов (minor / major / critical) */}
        <div className="card">
          <div className="card__title">Тяжесть отказов</div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={sevData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="name" fontSize={12} />
              <YAxis fontSize={12} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {sevData.map((d, i) => <Cell key={i} fill={d.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Гистограмма структуры парка: сколько активов в каждом статусе */}
        <div className="card">
          <div className="card__title">Структура парка</div>
          {summary && (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={[
                { name: "Активны",      value: summary.active,         fill: "#16a34a" },
                { name: "В ремонте",    value: summary.in_maintenance, fill: "#2563eb" },
                { name: "Авария",       value: summary.failed,         fill: "#dc2626" },
              ]}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="name" fontSize={12} />
                <YAxis fontSize={12} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {[
                    "#16a34a", "#2563eb", "#dc2626"
                  ].map((c, i) => <Cell key={i} fill={c} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Таблица последних 20 отказов ─────────────────────────── */}
      <div className="card">
        <div className="card__title">Последние отказы</div>
        {failures.length === 0 ? <div className="empty">Отказов нет.</div> : (
          <table className="table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>Объект (ID)</th>
                <th>Тип</th>
                <th>Тяжесть</th>
                <th>Простой, ч</th>
                <th>Причина</th>
              </tr>
            </thead>
            <tbody>
              {failures.slice(0, 20).map((f) => (
                <tr key={f.id}>
                  <td>{new Date(f.failed_at).toLocaleDateString("ru-RU")}</td>
                  <td>#{f.asset_id}</td>
                  <td>{f.failure_type || "—"}</td>
                  <td>
                    {/* Бейдж тяжести: critical→красный, major→жёлтый, minor→зелёный */}
                    <span className={`badge ${
                      f.severity === "critical" ? "badge--high" :
                      f.severity === "major"    ? "badge--medium" : "badge--low"
                    }`}>
                      {SEVERITY_LABEL[f.severity] || f.severity}
                    </span>
                  </td>
                  <td>{f.downtime_hours?.toFixed(1) || "—"}</td>
                  <td>{f.root_cause || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
