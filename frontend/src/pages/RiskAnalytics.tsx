// RiskAnalytics.tsx — страница управления ML-моделью и просмотра прогноза отказов.
// Предоставляет три операции:
//   1. Пересчитать риски всех объектов — запускает FailurePredictor по всем активам.
//   2. Переобучить модель — запускает train_model() с GridSearchCV (~1-3 мин на CPU).
//   3. Пересобрать цифровую копию — перестраивает NetworkX-граф из текущих данных БД.
// Показывает метрики текущей модели и полную таблицу объектов с фильтрами и сортировкой.

import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  calculateAllRisks, getModelMetrics, getAllRiskAssets,
  retrainModel, rebuildTwin,
} from "../api/client";
import type { ModelMetrics, TopRiskAsset } from "../types";
import RiskBadge from "../components/RiskBadge";
import StatCard from "../components/StatCard";
import { Loading, Spinner } from "../components/Loading";

// Поля, по которым можно сортировать таблицу
type SortField = "prob" | "criticality" | "name" | "region";
type SortDir   = "desc" | "asc";

export default function RiskAnalytics() {
  const [metrics, setMetrics] = useState<ModelMetrics | null>(null);
  // Загружаем до 500 объектов с рассчитанными рисками
  const [all, setAll] = useState<TopRiskAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [busyCalc, setBusyCalc] = useState(false);
  const [busyTrain, setBusyTrain] = useState(false);
  const [busyTwin, setBusyTwin] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Состояние фильтров и сортировки таблицы
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState<"" | "high" | "medium" | "low">("");
  const [regionFilter, setRegionFilter] = useState("");
  const [sortField, setSortField] = useState<SortField>("prob");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const loadAll = () => {
    setLoading(true);
    Promise.all([getModelMetrics(), getAllRiskAssets()])
      .then(([m, t]) => { setMetrics(m); setAll(t); })
      .catch((e) => setErr(e?.message || "Ошибка загрузки"))
      .finally(() => setLoading(false));
  };
  useEffect(loadAll, []);

  // Парсер времени из бэка (UTC без TZ-суффикса) с приведением к Екатеринбургу.
  // ВАЖНО: расчёт через useMemo должен быть ДО условных return,
  // иначе нарушаются «правила хуков» React (и страница падает в белый экран).
  const parseUtc = (s?: string | null) =>
    s ? new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : s + "Z") : null;
  const fmtEkb = (d: Date | null) =>
    d ? d.toLocaleString("ru-RU", {
      day: "2-digit", month: "long", year: "numeric",
      hour: "2-digit", minute: "2-digit",
      timeZone: "Asia/Yekaterinburg",
    }) + " (Екб)" : "—";
  const lastRiskCalcAt = useMemo(() => {
    const ts = all
      .map((a) => parseUtc(a.calculated_at)?.getTime())
      .filter((t): t is number => typeof t === "number");
    return ts.length ? new Date(Math.max(...ts)) : null;
  }, [all]);
  const modelTrainedAt = parseUtc(metrics?.trained_at);

  const handleCalc = async () => {
    setBusyCalc(true); setMsg(null);
    try {
      const res = await calculateAllRisks();
      setMsg(`✅ Рассчитано рисков: ${res.calculated}`);
      loadAll();
    } catch (e: any) { setMsg(`❌ ${e?.message || "Ошибка"}`); }
    finally { setBusyCalc(false); }
  };

  const handleRetrain = async () => {
    setBusyTrain(true); setMsg(null);
    try {
      const res = await retrainModel();
      setMsg(`✅ Модель переобучена. AUC=${res.metrics.roc_auc}, F1=${res.metrics.f1_macro}`);
      loadAll();
    } catch (e: any) { setMsg(`❌ ${e?.message || "Ошибка"}`); }
    finally { setBusyTrain(false); }
  };

  const handleTwin = async () => {
    setBusyTwin(true); setMsg(null);
    try {
      const res = await rebuildTwin();
      setMsg(`✅ Цифровая копия пересобрана: ${res.nodes} узлов, ${res.edges} рёбер`);
    } catch (e: any) { setMsg(`❌ ${e?.message || "Ошибка"}`); }
    finally { setBusyTwin(false); }
  };

  // Уникальные регионы из загруженных данных
  const regions = useMemo(() => {
    const s = new Set(all.map((a) => a.region).filter(Boolean));
    return Array.from(s).sort();
  }, [all]);

  // Переключение колонки сортировки: повторный клик меняет направление
  const toggleSort = (field: SortField) => {
    if (sortField === field) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortField(field); setSortDir("desc"); }
  };

  // Иконка стрелки сортировки
  const sortIcon = (field: SortField) =>
    sortField !== field ? " ↕" : sortDir === "desc" ? " ↓" : " ↑";

  // Применяем фильтры и сортировку на клиенте
  const filtered = useMemo(() => {
    let rows = [...all];
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (a) => a.asset_name.toLowerCase().includes(q) ||
               (a.region || "").toLowerCase().includes(q),
      );
    }
    if (levelFilter) rows = rows.filter((a) => a.risk_level === levelFilter);
    if (regionFilter) rows = rows.filter((a) => a.region === regionFilter);

    rows.sort((a, b) => {
      let va: number | string, vb: number | string;
      if (sortField === "prob") {
        // null считается как 0 (объекты без риска — в конце при сортировке по убыванию)
        va = a.risk_prob ?? -1; vb = b.risk_prob ?? -1;
      } else if (sortField === "criticality") { va = a.criticality; vb = b.criticality; }
      else if (sortField === "name")   { va = a.asset_name;  vb = b.asset_name; }
      else                             { va = a.region || ""; vb = b.region || ""; }
      if (va < vb) return sortDir === "desc" ? 1 : -1;
      if (va > vb) return sortDir === "desc" ? -1 : 1;
      return 0;
    });
    return rows;
  }, [all, search, levelFilter, regionFilter, sortField, sortDir]);

  // Счётчики по уровням для KPI-карточек таблицы
  const highCount    = all.filter((a) => a.risk_level === "high").length;
  const medCount     = all.filter((a) => a.risk_level === "medium").length;
  const lowCount     = all.filter((a) => a.risk_level === "low").length;
  const noRiskCount  = all.filter((a) => a.risk_level === null).length;

  if (loading) return <Loading />;
  if (err) return <div className="error">{err}</div>;

  return (
    <div>
      <h1>Прогноз отказов</h1>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Прогноз вероятности отказа на горизонте{" "}
        <strong>{metrics?.forecast_horizon_days ?? 90} дней</strong>{" "}
        на основе ансамбля Random Forest + Gradient Boosting,
        обученного на 10 000 синтетических примерах, 19 признаках.
      </p>

      {/* ── Плашка: когда последний раз пересчитывали риски и обучали модель ── */}
      <div className="card" style={{
        marginBottom: 16,
        borderLeft: "4px solid #2563eb",
        padding: "10px 14px",
        display: "flex", gap: 20, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Риски пересчитаны
          </div>
          <div style={{ fontWeight: 600, fontSize: 13, marginTop: 2 }}>
            {fmtEkb(lastRiskCalcAt)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Модель обучена
          </div>
          <div style={{ fontWeight: 600, fontSize: 13, marginTop: 2 }}>
            {fmtEkb(modelTrainedAt)}
          </div>
        </div>
      </div>

      {/* ── Панель управления операциями ─────────────────────────── */}
      <div className="card">
        <div className="card__title">Действия</div>
        <div className="row">
          <button className="btn btn--primary" onClick={handleCalc} disabled={busyCalc}>
            {busyCalc ? <><Spinner /> Расчёт...</> : "Пересчитать риски всех объектов"}
          </button>
          <button className="btn btn--ghost" onClick={handleRetrain} disabled={busyTrain}>
            {busyTrain ? <><Spinner /> Обучение...</> : "Переобучить модель"}
          </button>
          <button className="btn btn--ghost" onClick={handleTwin} disabled={busyTwin}>
            {busyTwin ? <><Spinner /> Сборка...</> : "Пересобрать цифровую копию"}
          </button>
        </div>
        {msg && <div style={{ marginTop: 12, fontSize: 13 }}>{msg}</div>}
      </div>

      {/* ── Метрики модели ───────────────────────────────────────── */}
      <div className="stat-grid">
        <StatCard label="Версия модели" value={metrics?.model_version || "—"} />
        <StatCard label="Горизонт прогноза" value={metrics?.forecast_horizon_days ?? 90} hint="дней" accent="success" />
        <StatCard label="ROC-AUC"       value={metrics?.roc_auc?.toFixed(3) || "—"} hint="на тестовой выборке" />
        <StatCard label="F1-macro"      value={metrics?.f1_macro?.toFixed(3) || "—"} />
        <StatCard label="Размер train"  value={metrics?.n_train ?? "—"} />
        <StatCard label="Размер test"   value={metrics?.n_test ?? "—"} />
        <StatCard label="Доля положит." value={metrics?.positive_rate != null ? `${(metrics.positive_rate * 100).toFixed(1)}%` : "—"} />
      </div>

      {/* ── Признаки модели ──────────────────────────────────────── */}
      <div className="card">
        <div className="card__title">Признаки модели</div>
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          {(metrics?.feature_columns || []).map((f) => (
            <span key={f} className="badge badge--neutral">{f}</span>
          ))}
        </div>
        <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
          Обучена: {metrics?.trained_at ? new Date(metrics.trained_at).toLocaleString("ru-RU") : "—"}
        </div>
      </div>

      {/* ── Таблица всех объектов с фильтрами ───────────────────── */}
      <div className="card" style={{ padding: 0 }}>
        {/* Шапка блока с счётчиками */}
        <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #e5e7eb" }}>
          <div className="row-between" style={{ marginBottom: 12 }}>
            <div className="card__title" style={{ margin: 0 }}>
              Все объекты по уровню риска
              <span className="muted" style={{ fontWeight: 400, marginLeft: 8 }}>
                ({filtered.length} из {all.length})
              </span>
            </div>
            {/* Мини-счётчики по уровням */}
            <div className="row" style={{ gap: 8 }}>
              <span className="badge risk-high">{highCount} высокий</span>
              <span className="badge risk-medium">{medCount} средний</span>
              <span className="badge risk-low">{lowCount} низкий</span>
              {noRiskCount > 0 && (
                <span className="badge badge--neutral">{noRiskCount} без расчёта</span>
              )}
            </div>
          </div>

          {/* Строка фильтров */}
          <div className="filters" style={{ marginBottom: 0 }}>
            <input
              className="input" placeholder="Поиск по имени / региону..."
              value={search} onChange={(e) => setSearch(e.target.value)}
              style={{ flex: 1, minWidth: 200 }}
            />
            <select className="select" value={levelFilter}
                    onChange={(e) => setLevelFilter(e.target.value as any)}>
              <option value="">Все уровни</option>
              <option value="high">Высокий</option>
              <option value="medium">Средний</option>
              <option value="low">Низкий</option>
            </select>
            <select className="select" value={regionFilter}
                    onChange={(e) => setRegionFilter(e.target.value)}>
              <option value="">Все регионы</option>
              {regions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
        </div>

        {/* Таблица */}
        {all.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>
            Нажмите «Пересчитать риски всех объектов»
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>Объектов не найдено.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>#</th>
                {/* Кликабельные заголовки для сортировки */}
                <th style={{ cursor: "pointer" }} onClick={() => toggleSort("name")}>
                  Объект{sortIcon("name")}
                </th>
                <th style={{ cursor: "pointer" }} onClick={() => toggleSort("region")}>
                  Регион{sortIcon("region")}
                </th>
                <th style={{ cursor: "pointer", whiteSpace: "nowrap" }} onClick={() => toggleSort("prob")}>
                  Вероятность отказа за {metrics?.forecast_horizon_days ?? 90} дней{sortIcon("prob")}
                </th>
                <th>Уровень риска</th>
                <th style={{ cursor: "pointer" }} onClick={() => toggleSort("criticality")}>
                  Критичность{sortIcon("criticality")}
                </th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a, i) => (
                <tr key={a.asset_id}
                    style={a.risk_level === "high"   ? { background: "#fff5f5" } :
                           a.risk_level === "medium" ? { background: "#fffbeb" } : undefined}>
                  <td className="muted" style={{ fontSize: 12 }}>{i + 1}</td>
                  <td>{a.asset_name}</td>
                  <td>{a.region}</td>
                  {/* Полоска вероятности — пустая если риск не рассчитан */}
                  <td>
                    {a.risk_prob != null ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{ flex: 1, background: "#e5e7eb", borderRadius: 4, height: 6, minWidth: 60 }}>
                          <div style={{
                            height: 6, borderRadius: 4,
                            width: `${(a.risk_prob * 100).toFixed(0)}%`,
                            background: a.risk_level === "high"   ? "#dc2626" :
                                        a.risk_level === "medium" ? "#f59e0b" : "#16a34a",
                          }} />
                        </div>
                        <span style={{ fontSize: 13, minWidth: 40 }}>
                          {(a.risk_prob * 100).toFixed(1)}%
                        </span>
                      </div>
                    ) : (
                      <span className="muted" style={{ fontSize: 12 }}>не рассчитан</span>
                    )}
                  </td>
                  <td><RiskBadge level={a.risk_level} probability={a.risk_prob} /></td>
                  <td>{(a.criticality * 100).toFixed(0)}%</td>
                  <td><Link to={`/assets/${a.asset_id}`}>Карточка →</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
