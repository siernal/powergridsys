// RepairsList.tsx — общий журнал всех ремонтов и ТО (страница «Ремонты»).
// Загружает последние записи через GET /api/repairs и сопоставляет каждый
// ремонт с объектом через локальный словарь, заполняемый из GET /api/assets.

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { listRepairs, listAssets, deleteRepair } from "../api/client";
import type { Repair, Asset } from "../types";
import { Loading } from "../components/Loading";
import Modal from "../components/Modal";
import StatCard from "../components/StatCard";
import RepairForm from "../components/forms/RepairForm";

const REPAIR_TYPE_LABEL: Record<string, string> = {
  planned: "Плановый",
  emergency: "Аварийный",
  capital: "Капитальный",
};

const fmtDate = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric",
                                     hour: "2-digit", minute: "2-digit" });
};

const fmtMoney = (n?: number | null) =>
  n == null ? "—" : new Intl.NumberFormat("ru-RU").format(n) + " ₽";

export default function RepairsList() {
  const [repairs, setRepairs] = useState<Repair[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Фильтры
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  // Модалка редактирования
  const [editing, setEditing] = useState<Repair | null>(null);

  const fetchAll = () => {
    setLoading(true);
    Promise.all([listRepairs(), listAssets({ limit: 1000 })])
      .then(([rs, as]) => {
        setRepairs(rs);
        setAssets(as);
        setErr(null);
      })
      .catch((e) => setErr(e?.message || "Ошибка загрузки"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  // Словарь id→объект для подстановки имени и ссылки в таблицу
  const assetMap = useMemo(() => {
    const m = new Map<number, Asset>();
    assets.forEach((a) => m.set(a.id, a));
    return m;
  }, [assets]);

  const filtered = useMemo(() => {
    let rs = repairs;
    if (typeFilter) rs = rs.filter((r) => r.repair_type === typeFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      rs = rs.filter((r) => {
        const a = assetMap.get(r.asset_id);
        return (a?.name || "").toLowerCase().includes(q) ||
               (r.performed_by || "").toLowerCase().includes(q) ||
               (r.work_description || "").toLowerCase().includes(q);
      });
    }
    return rs;
  }, [repairs, assetMap, typeFilter, search]);

  const onDelete = async (r: Repair) => {
    if (!confirm(`Удалить запись о ремонте #${r.id}?`)) return;
    try {
      await deleteRepair(r.id);
      fetchAll();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Ошибка удаления");
    }
  };

  // Сводка по типам
  const summary = useMemo(() => {
    const s = { total: repairs.length, planned: 0, emergency: 0, capital: 0,
                totalCost: 0 };
    repairs.forEach((r) => {
      if (r.repair_type === "planned") s.planned += 1;
      else if (r.repair_type === "emergency") s.emergency += 1;
      else if (r.repair_type === "capital") s.capital += 1;
      if (r.cost) s.totalCost += Number(r.cost);
    });
    return s;
  }, [repairs]);

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 16 }}>
        <h1>Ремонты и техническое обслуживание</h1>
        <span className="muted">Найдено: {filtered.length}</span>
      </div>

      {/* ── Сводные карточки ────────────────────────────────────────── */}
      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <StatCard label="Всего ремонтов" value={summary.total} />
        <StatCard label="Плановых" value={summary.planned} accent="success" />
        <StatCard label="Аварийных" value={summary.emergency} accent="danger" />
        <StatCard label="Капитальных" value={summary.capital} />
        <StatCard label="Суммарная стоимость" value={fmtMoney(summary.totalCost)} />
      </div>

      {/* ── Фильтры ─────────────────────────────────────────────────── */}
      <div className="filters">
        <input className="input" placeholder="Поиск по объекту / исполнителю / описанию..."
               value={search} onChange={(e) => setSearch(e.target.value)}
               style={{ flex: 1, minWidth: 240 }} />
        <select className="select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">Все типы</option>
          <option value="planned">Плановые</option>
          <option value="emergency">Аварийные</option>
          <option value="capital">Капитальные</option>
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
                <th>Тип</th>
                <th>Начат</th>
                <th>Завершён</th>
                <th>Стоимость</th>
                <th>Исполнитель</th>
                <th>Описание работ</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const a = assetMap.get(r.asset_id);
                return (
                  <tr key={r.id}>
                    <td>#{r.id}</td>
                    <td>{a ? <Link to={`/assets/${a.id}`}>{a.name}</Link> : `#${r.asset_id}`}</td>
                    <td>
                      <span className={`badge badge--${r.repair_type}`}>
                        {REPAIR_TYPE_LABEL[r.repair_type] || r.repair_type}
                      </span>
                    </td>
                    <td>{fmtDate(r.started_at)}</td>
                    <td>{r.completed_at ? fmtDate(r.completed_at)
                                        : <span className="muted">в работе</span>}</td>
                    <td>{fmtMoney(r.cost)}</td>
                    <td>{r.performed_by || "—"}</td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {r.work_description || "—"}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <button className="btn btn--ghost btn--sm" title="Редактировать"
                                onClick={() => setEditing(r)}>✎</button>
                        <button className="btn btn--ghost btn--sm" title="Удалить"
                                onClick={() => onDelete(r)}>🗑</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filtered.length === 0 && <div className="empty">Ремонтов не найдено.</div>}
        </div>
      )}

      {/* ── Модалка редактирования ─────────────────────────────────── */}
      <Modal
        open={!!editing}
        title={editing ? `Редактирование ремонта #${editing.id}` : ""}
        onClose={() => setEditing(null)}
        width={640}
      >
        {editing && (
          <RepairForm
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
