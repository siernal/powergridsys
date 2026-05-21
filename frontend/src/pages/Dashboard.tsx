// Dashboard.tsx — главная страница (дашборд).
// Отображает KPI-панель, круговую диаграмму рисков, гистограмму отказов по месяцам
// и таблицу топ-5 объектов по уровню риска.
// Все данные загружаются одним параллельным запросом через Promise.all.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import {
  getAnalyticsSummary, getRiskDistribution, getTopRiskAssets, getFailuresByMonth,
} from "../api/client";
import type { AnalyticsSummary, TopRiskAsset } from "../types";
import StatCard from "../components/StatCard";
import RiskBadge from "../components/RiskBadge";
import { Loading } from "../components/Loading";

// Цвета секторов в диаграмме рисков (low=зелёный, medium=жёлтый, high=красный)
const RISK_COLORS: Record<string, string> = {
  low: "#16a34a", medium: "#f59e0b", high: "#dc2626",
};

export default function Dashboard() {
  // Сводные KPI (количество объектов, риски, отказы)
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  // Распределение по уровням риска {low: N, medium: M, high: K}
  const [risk, setRisk] = useState<Record<string, number>>({});
  // Топ-5 объектов с наибольшим риском
  const [top, setTop] = useState<TopRiskAsset[]>([]);
  // Отказы по месяцам за последний год
  const [byMonth, setByMonth] = useState<{ month: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // Загружаем все 4 источника данных параллельно
    Promise.all([
      getAnalyticsSummary(), getRiskDistribution(),
      getTopRiskAssets(5), getFailuresByMonth(),
    ])
      .then(([s, r, t, m]) => { setSummary(s); setRisk(r); setTop(t); setByMonth(m); })
      .catch((e) => setErr(e?.message || "Ошибка загрузки"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading />;
  if (err) return <div className="error">{err}</div>;
  if (!summary) return null;

  // Преобразуем словарь {low:N, ...} в массив для recharts с русскими метками
  const riskData = Object.entries(risk).map(([level, count]) => ({
    name: level === "low" ? "Низкий" : level === "medium" ? "Средний" : "Высокий",
    value: count,
    level,
  }));

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 16 }}>
        <h1>Дашборд</h1>
        <span className="muted">Обновлено только что</span>
      </div>

      {/* ── KPI-карточки ─────────────────────────────────────────── */}
      <div className="stat-grid">
        <StatCard label="Объектов в сети"      value={summary.total_assets}   hint="всего на балансе" />
        <StatCard label="Активных"             value={summary.active}          accent="success" />
        <StatCard label="В обслуживании"       value={summary.in_maintenance} />
        <StatCard label="В аварии"             value={summary.failed}          accent="danger" />
        <StatCard label="Высокий риск"         value={summary.high_risk_count} accent="danger"
                  hint={`+${summary.medium_risk_count} среднего риска`} />
        <StatCard label="Индекс состояния"     value={summary.avg_health_score?.toFixed(1) ?? "—"}
                  hint="по цифровой копии" />
        <StatCard label="Отказов за год"       value={summary.total_failures_last_year} />
        <StatCard label="Запл. работ (30 дн.)" value={summary.upcoming_maintenance_count} />
      </div>

      {/* ── Диаграммы ────────────────────────────────────────────── */}
      <div className="grid-2">
        {/* Круговая диаграмма распределения рисков */}
        <div className="card">
          <div className="card__title">Распределение объектов по уровню риска</div>
          {riskData.length === 0 ? (
            <div className="empty">Риски ещё не рассчитаны.<br/>
              <Link to="/risk">Перейти в раздел «Прогноз отказов» →</Link>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={riskData} dataKey="value" nameKey="name" outerRadius={90} label>
                  {riskData.map((d) => (
                    <Cell key={d.level} fill={RISK_COLORS[d.level]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Гистограмма отказов по месяцам */}
        <div className="card">
          <div className="card__title">Отказы по месяцам (последний год)</div>
          {byMonth.length === 0 ? (
            <div className="empty">Нет данных.</div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={byMonth}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="month" fontSize={12} />
                <YAxis fontSize={12} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#2563eb" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Таблица топ-5 объектов по риску ──────────────────────── */}
      <div className="card">
        <div className="card__title">Топ-5 объектов по риску</div>
        {top.length === 0 ? (
          <div className="empty">
            Сначала рассчитайте риски: <Link to="/risk">Прогноз отказов</Link>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Объект</th>
                <th>Регион</th>
                <th>Риск</th>
                <th>Критичность</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {top.map((a) => (
                <tr key={a.asset_id}>
                  <td>{a.asset_name}</td>
                  <td>{a.region}</td>
                  <td><RiskBadge level={a.risk_level} probability={a.risk_prob} /></td>
                  <td>{(a.criticality * 100).toFixed(0)}%</td>
                  <td><Link to={`/assets/${a.asset_id}`}>Подробнее →</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
