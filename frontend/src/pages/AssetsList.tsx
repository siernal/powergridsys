// AssetsList.tsx — реестр объектов электросети с поддержкой CRUD.
// Серверные фильтры (category/region/status) + клиентский поиск по тексту.
// Действия в строках: «✎» — редактировать (открывает модальную форму),
// «🗑» — удалить (с подтверждением). Кнопка «➕ Добавить» сверху.

import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { listAssets, deleteAsset } from "../api/client";
import type { Asset } from "../types";
import { Loading } from "../components/Loading";
import Modal from "../components/Modal";
import AssetForm from "../components/forms/AssetForm";

const CATEGORY_LABEL: Record<string, string> = {
  transformer: "Трансформатор",
  line: "Линия",
  substation: "Подстанция",
  cable: "Кабель",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Активен",
  maintenance: "В ремонте",
  failed: "Авария",
  decommissioned: "Списан",
};

export default function AssetsList() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Серверные фильтры
  const [category, setCategory] = useState("");
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");

  // Состояние модального окна: режим (create/edit) и редактируемый объект
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);

  const fetchAssets = () => {
    setLoading(true);
    listAssets({ category: category || undefined, region: region || undefined,
                 status: status || undefined, limit: 500 })
      .then(setAssets)
      .catch((e) => setErr(e?.message || "Ошибка загрузки"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAssets(); /* eslint-disable-next-line */ }, [category, region, status]);

  const regions = useMemo(() => {
    const set = new Set(assets.map((a) => a.region).filter(Boolean) as string[]);
    return Array.from(set).sort();
  }, [assets]);

  const filtered = useMemo(() => {
    if (!search.trim()) return assets;
    const q = search.toLowerCase();
    return assets.filter(
      (a) => a.name.toLowerCase().includes(q) ||
             (a.region || "").toLowerCase().includes(q),
    );
  }, [assets, search]);

  // Открыть форму в режиме создания
  const onAdd = () => { setEditing(null); setModalOpen(true); };
  // Открыть форму в режиме редактирования
  const onEdit = (a: Asset) => { setEditing(a); setModalOpen(true); };
  // Удалить с подтверждением
  const onDelete = async (a: Asset) => {
    if (!confirm(`Удалить объект «${a.name}»?\nБудут удалены все осмотры, ремонты, отказы и риск-скоры этого объекта.`)) return;
    try {
      await deleteAsset(a.id);
      fetchAssets();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Ошибка удаления");
    }
  };

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 16 }}>
        <h1>Реестр объектов электросети</h1>
        <div className="row" style={{ gap: 12, alignItems: "center" }}>
          <span className="muted">Найдено: {filtered.length}</span>
          <button className="btn btn--primary" onClick={onAdd}>➕ Добавить объект</button>
        </div>
      </div>

      {/* ── Панель фильтров ────────────────────────────────────────── */}
      <div className="filters">
        <input className="input" placeholder="Поиск по имени / региону..."
               value={search} onChange={(e) => setSearch(e.target.value)}
               style={{ flex: 1, minWidth: 240 }} />
        <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Все типы</option>
          <option value="transformer">Трансформаторы</option>
          <option value="line">Линии</option>
          <option value="substation">Подстанции</option>
          <option value="cable">Кабели</option>
        </select>
        <select className="select" value={region} onChange={(e) => setRegion(e.target.value)}>
          <option value="">Все регионы</option>
          {regions.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все статусы</option>
          <option value="active">Активен</option>
          <option value="maintenance">В ремонте</option>
          <option value="failed">Авария</option>
          <option value="decommissioned">Списан</option>
        </select>
      </div>

      {/* ── Таблица активов ────────────────────────────────────────── */}
      {loading ? <Loading /> :
       err ? <div className="error">{err}</div> :
       (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Наименование</th>
                <th>Тип</th>
                <th>Напряжение</th>
                <th>Регион</th>
                <th>Дата установки</th>
                <th>Критичность</th>
                <th>Статус</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id}>
                  <td>#{a.id}</td>
                  <td><Link to={`/assets/${a.id}`}>{a.name}</Link></td>
                  <td>{CATEGORY_LABEL[a.asset_type?.category || ""] || a.asset_type?.category}</td>
                  <td>{a.voltage_class || "—"}</td>
                  <td>{a.region || "—"}</td>
                  <td>{a.installed_date || "—"}</td>
                  <td>{(a.criticality * 100).toFixed(0)}%</td>
                  <td>
                    <span className={`badge badge--${a.status}`}>
                      {STATUS_LABEL[a.status] || a.status}
                    </span>
                  </td>
                  {/* Колонка действий: маленькие кнопки edit/delete */}
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <button className="btn btn--ghost btn--sm" title="Редактировать"
                              onClick={() => onEdit(a)}>✎</button>
                      <button className="btn btn--ghost btn--sm" title="Удалить"
                              onClick={() => onDelete(a)}>🗑</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && <div className="empty">Объектов не найдено.</div>}
        </div>
       )}

      {/* ── Модальное окно создания/редактирования ───────────────── */}
      <Modal
        open={modalOpen}
        title={editing ? `Редактирование объекта #${editing.id}` : "Новый объект"}
        onClose={() => setModalOpen(false)}
        width={720}
      >
        <AssetForm
          initial={editing}
          onCancel={() => setModalOpen(false)}
          onDone={() => { setModalOpen(false); fetchAssets(); }}
        />
      </Modal>
    </div>
  );
}
