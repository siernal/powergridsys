// FailuresList.tsx — общий журнал всех отказов оборудования (страница «Отказы»).
// Загружает последние записи через GET /api/failures и сопоставляет каждый
// отказ с объектом через локальный словарь, заполняемый из GET /api/assets.

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { listFailures, listAssets, deleteFailure } from "../api/client";
import type { Failure, Asset } from "../types";
import { Loading } from "../components/Loading";
import Modal from "../components/Modal";
import StatCard from "../components/StatCard";
import FailureForm from "../components/forms/FailureForm";

const SEVERITY_LABEL: Record<string, string> = {
  minor: "Незначительный",
  major: "Серьёзный",
  critical: "Критический",
};

const SEVERITY_COLOR: Record<string, string> = {
  minor: "#f59e0b",
  major: "#ef4444",
  critical: "#7f1d1d",
};

const fmtDate = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric",
                                     hour: "2-digit", minute: "2-digit" });
};

export default function FailuresList() {
  const [failures, setFailures] = useState<Failure[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Фильтры
  const [search, setSearch] = useState("");
  const [sevFilter, setSevFilter] = useState("");

  // Модалка
  const [editing, setEditing] = useState<Failure | null>(null);

  const fetchAll = () => {
    setLoading(true);
    Promise.all([listFailures(), listAssets({ limit: 1000 })])
      .then(([fs, as]) => {
        setFailures(fs);
        setAssets(as);
        setErr(null);
      })
      .catch((e) => setErr(e?.message || "Ошибка загрузки"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  const assetMap = useMemo(() => {
    const m = new Map<number, Asset>();
    assets.forEach((a) => m.set(a.id, a));
    return m;
  }, [assets]);

  const filtered = useMemo(() => {
    let fs = failures;
    if (sevFilter) fs = fs.filter((f) => f.severity === sevFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      fs = fs.filter((f) => {
        const a = assetMap.get(f.asset_id);
        return (a?.name || "").toLowerCase().includes(q) ||
               (f.failure_type || "").toLowerCase().includes(q) ||
               (f.root_cause || "").toLowerCase().includes(q);
      });
    }
    return fs;
  }, [failures, assetMap, sevFilter, search]);

  const onDelete = async (f: Failure) => {
    if (!confirm(`Удалить запись об отказе #${f.id}?`)) return;
    try {
      await deleteFailure(f.id);
      fetchAll();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Ошибка удаления");
    }
  };

  // Сводная статистика
  const summary = useMemo(() => {
    const s = { total: failures.length, minor: 0, major: 0, critical: 0,
                totalDowntime: 0, resolved: 0, unresolved: 0 };
    failures.forEach((f) => {
      if (f.severity === "minor") s.minor += 1;
      else if (f.severity === "major") s.major += 1;
      else if (f.severity === "critical") s.critical += 1;
      if (f.downtime_hours) s.totalDowntime += Number(f.downtime_hours);
      if (f.resolved_at) s.resolved += 1; else s.unresolved += 1;
    });
    return s;
  }, [failures]);

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 16 }}>
        <h1>Отказы оборудования</h1>
        <span className="muted">Найдено: {filtered.length}</span>
      </div>

      {/* ── KPI-карточки ────────────────────────────────────────────── */}
      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <StatCard label="Всего отказов" value={summary.total} />
        <StatCard label="Критических" value={summary.critical} accent="danger" />
        <StatCard label="Серьёзных" value={summary.major} accent="warning" />
        <StatCard label="Незначительных" value={summary.minor} />
        <StatCard label="Не устранено" value={summary.unresolved} accent="danger" />
        <StatCard label="Суммарный простой" value={`${summary.totalDowntime.toFixed(0)} ч`} />
      </div>

      {/* ── Фильтры ─────────────────────────────────────────────────── */}
      <div className="filters">
        <input className="input" placeholder="Поиск по объекту / типу / причине..."
               value={search} onChange={(e) => setSearch(e.target.value)}
               style={{ flex: 1, minWidth: 240 }} />
        <select className="select" value={sevFilter} onChange={(e) => setSevFilter(e.target.value)}>
          <option value="">Все степени тяжести</option>
          <option value="critical">Критические</option>
          <option value="major">Серьёзные</option>
          <option value="minor">Незначительные</option>
        </select>
      </div>

      {/* ── Таблица ─────────────────────────────────────────────────── */}
      {loading ? <Loading /> :
       err ? <div className="error">{err}</div> : (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Объект</th>
                <th>Произошёл</th>
                <th>Тип отказа</th>
                <th>Тяжесть</th>
                <th>Простой, ч</th>
                <th>Устранён</th>
                <th>Причина</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((f) => {
                const a = assetMap.get(f.asset_id);
                return (
                  <tr key={f.id}>
                    <td>#{f.id}</td>
                    <td>{a ? <Link to={`/assets/${a.id}`}>{a.name}</Link> : `#${f.asset_id}`}</td>
                    <td>{fmtDate(f.failed_at)}</td>
                    <td>{f.failure_type || "—"}</td>
                    <td>
                      <span style={{
                        background: SEVERITY_COLOR[f.severity] || "#94a3b8",
                        color: "white", padding: "2px 8px", borderRadius: 4,
                        fontSize: 12, fontWeight: 600,
                      }}>
                        {SEVERITY_LABEL[f.severity] || f.severity}
                      </span>
                    </td>
                    <td>{f.downtime_hours != null ? f.downtime_hours.toFixed(1) : "—"}</td>
                    <td>{f.resolved_at ? fmtDate(f.resolved_at)
                                       : <span style={{ color: "#ef4444" }}>не устранён</span>}</td>
                    <td style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {f.root_cause || "—"}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <button className="btn btn--ghost btn--sm" title="Редактировать"
                                onClick={() => setEditing(f)}>✎</button>
                        <button className="btn btn--ghost btn--sm" title="Удалить"
                                onClick={() => onDelete(f)}>🗑</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filtered.length === 0 && <div className="empty">Отказов не найдено.</div>}
        </div>
      )}

      {/* ── Модалка редактирования ─────────────────────────────────── */}
      <Modal
        open={!!editing}
        title={editing ? `Редактирование отказа #${editing.id}` : ""}
        onClose={() => setEditing(null)}
        width={640}
      >
        {editing && (
          <FailureForm
            initial={editing}
            assetId={editing.asset_id}
            onCancel={() => setEditing(null)}
            onDone={() => { setEditing(null); fetchAll(); }}
          />
        )}
      </Modal>
    </div>
  );
}
