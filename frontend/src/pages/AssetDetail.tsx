// AssetDetail.tsx — карточка одного объекта с поддержкой CRUD.
// Помимо просмотра карточки и истории, позволяет:
//   - редактировать сам объект и удалить его (вверху страницы);
//   - добавлять/редактировать/удалять записи осмотров, ремонтов, отказов
//     (кнопки в шапках соответствующих блоков и в каждой строке).
// Все формы открываются в общей универсальной модалке.

import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
  getAsset, getAssetInspections, getAssetRepairs, getAssetFailures,
  calculateRisk, getTwinNode,
  deleteAsset, deleteInspection, deleteRepair, deleteFailure,
  uploadAssetImage, deleteAssetImage, staticBaseUrl,
} from "../api/client";
import type { AssetDetail, Inspection, Repair, Failure } from "../types";
import RiskBadge from "../components/RiskBadge";
import StatCard from "../components/StatCard";
import { Loading, Spinner } from "../components/Loading";
import Modal from "../components/Modal";
import AssetForm from "../components/forms/AssetForm";
import InspectionForm from "../components/forms/InspectionForm";
import RepairForm from "../components/forms/RepairForm";
import FailureForm from "../components/forms/FailureForm";

const SEVERITY_LABEL: Record<string, string> = {
  minor: "Незначительная", major: "Серьёзная", critical: "Критическая",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Активен", maintenance: "В ремонте", failed: "Авария", decommissioned: "Списан",
};

const REPAIR_TYPE_LABEL: Record<string, string> = {
  planned: "Плановый", emergency: "Аварийный", capital: "Капитальный",
};

const CATEGORY_LABEL: Record<string, string> = {
  transformer: "Трансформатор", line: "Линия", substation: "Подстанция", cable: "Кабель",
};

// Человеко-читаемые подписи для факторов breakdown (категория → factor → label)
const FACTOR_LABEL: Record<string, string> = {
  age: "Возраст",
  failures: "Накопленные отказы",
  repairs: "Выполненные ремонты",
  load: "Тепловая нагрузка изоляции",
  overload_spike: "Острая перегрузка (>90%)",
  maintenance_lag: "Давность диагностики",
  temperature: "Экстремальная температура",
  storm: "Штормовое воздействие",
  weather_storm: "Погодные нагрузки (ветер, гололёд, гроза)",
  switch_cycles: "Износ коммутационного ресурса",
  load_marginal: "Токовая нагрузка проводов",
  thermal_load: "Перегрев в грунте",
  soil_cold: "Промерзание грунта",
  criticality_amp: "Усиление по критичности",
};

// Какие параметры показывать в шапке twin-карточки в зависимости от категории
const CATEGORY_PARAMS: Record<string, { label: string; key: "load" | "age_ratio"; suffix: string }[]> = {
  transformer: [
    { label: "Нагрузка масла",       key: "load",      suffix: " %" },
    { label: "Выработка ресурса",    key: "age_ratio", suffix: "" },
  ],
  substation: [
    { label: "Загрузка коммутации",  key: "load",      suffix: " %" },
    { label: "Выработка ресурса",    key: "age_ratio", suffix: "" },
  ],
  line: [
    { label: "Загрузка по току",     key: "load",      suffix: " %" },
    { label: "Выработка ресурса",    key: "age_ratio", suffix: "" },
  ],
  cable: [
    { label: "Тепловой режим",       key: "load",      suffix: " %" },
    { label: "Выработка ресурса",    key: "age_ratio", suffix: "" },
  ],
};

// Возможные модальные окна на странице
type ModalKind =
  | null
  | { kind: "asset" }                            // редактирование объекта
  | { kind: "insp"; initial?: Inspection | null } // создание/редактирование осмотра
  | { kind: "rep";  initial?: Repair | null }     // создание/редактирование ремонта
  | { kind: "fail"; initial?: Failure | null };   // создание/редактирование отказа

export default function AssetDetailPage() {
  const { id } = useParams();
  const assetId = Number(id);
  const navigate = useNavigate();

  const [asset, setAsset] = useState<AssetDetail | null>(null);
  const [insp, setInsp] = useState<Inspection[]>([]);
  const [reps, setReps] = useState<Repair[]>([]);
  const [fails, setFails] = useState<Failure[]>([]);   // новый список отказов
  const [twin, setTwin] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [calc, setCalc] = useState(false);
  const [uploadingImg, setUploadingImg] = useState(false);

  // Единое состояние модалок — null = закрыто
  const [modal, setModal] = useState<ModalKind>(null);

  // ─── Загрузка / удаление изображения объекта ──────────────────
  const onUploadImage = async (file: File) => {
    setUploadingImg(true);
    try {
      await uploadAssetImage(assetId, file);
      loadAll();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Ошибка загрузки изображения");
    } finally {
      setUploadingImg(false);
    }
  };
  const onDeleteImage = async () => {
    if (!confirm("Удалить изображение объекта?")) return;
    try { await deleteAssetImage(assetId); loadAll(); }
    catch (e: any) { alert(e?.response?.data?.detail || e?.message || "Ошибка"); }
  };

  const loadAll = () => {
    setLoading(true);
    Promise.all([
      getAsset(assetId),
      getAssetInspections(assetId),
      getAssetRepairs(assetId),
      getAssetFailures(assetId),
      getTwinNode(assetId).catch(() => null),
    ])
      .then(([a, i, r, f, t]) => {
        setAsset(a); setInsp(i); setReps(r); setFails(f); setTwin(t);
      })
      .catch((e) => setErr(e?.message || "Ошибка загрузки"))
      .finally(() => setLoading(false));
  };

  useEffect(loadAll, [assetId]);

  const onCalculate = async () => {
    setCalc(true);
    try { await calculateRisk(assetId); loadAll(); }
    catch (e: any) { alert(e?.message || "Ошибка"); }
    finally { setCalc(false); }
  };

  // ─── Удаление различных сущностей ──────────────────────────────
  const onDeleteAsset = async () => {
    if (!asset) return;
    if (!confirm(`Удалить объект «${asset.name}»?\nБудут удалены все осмотры, ремонты, отказы и риск-скоры.`)) return;
    try { await deleteAsset(assetId); navigate("/assets"); }
    catch (e: any) { alert(e?.response?.data?.detail || e?.message || "Ошибка"); }
  };
  const onDeleteInsp = async (x: Inspection) => {
    if (!confirm(`Удалить осмотр от ${new Date(x.inspected_at).toLocaleDateString("ru-RU")}?`)) return;
    try { await deleteInspection(x.id); loadAll(); }
    catch (e: any) { alert(e?.message || "Ошибка"); }
  };
  const onDeleteRep = async (x: Repair) => {
    if (!confirm("Удалить запись о ремонте?")) return;
    try { await deleteRepair(x.id); loadAll(); }
    catch (e: any) { alert(e?.message || "Ошибка"); }
  };
  const onDeleteFail = async (x: Failure) => {
    if (!confirm(`Удалить запись об отказе от ${new Date(x.failed_at).toLocaleDateString("ru-RU")}?`)) return;
    try { await deleteFailure(x.id); loadAll(); }
    catch (e: any) { alert(e?.message || "Ошибка"); }
  };

  // Закрытие модалки + перезагрузка данных после сохранения
  const closeReload = () => { setModal(null); loadAll(); };

  if (loading) return <Loading />;
  if (err) return <div className="error">{err}</div>;
  if (!asset) return <div className="empty">Не найдено</div>;

  const healthColor =
    (asset.health_score ?? 0) > 70 ? "success" :
    (asset.health_score ?? 0) > 40 ? "warning" : "danger";

  return (
    <div>
      {/* ── Заголовок с действиями ──────────────────────────────── */}
      <div className="row-between" style={{ marginBottom: 16 }}>
        <div>
          <Link to="/assets" className="muted">← К реестру</Link>
          <h1 style={{ marginTop: 6 }}>{asset.name}</h1>
          <span className="muted">
            {asset.asset_type?.name} · {asset.voltage_class} · {asset.region}
          </span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn btn--ghost" onClick={() => setModal({ kind: "asset" })}>✎ Редактировать</button>
          <button className="btn btn--ghost" onClick={onDeleteAsset}>🗑 Удалить</button>
          <button className="btn btn--primary" onClick={onCalculate} disabled={calc}>
            {calc ? <><Spinner /> Расчёт...</> : "🔮 Пересчитать риск"}
          </button>
        </div>
      </div>

      {/* ── KPI-карточки объекта ─────────────────────────────────── */}
      <div className="stat-grid">
        <StatCard label="Возраст" value={asset.age_years?.toFixed(1) ?? "—"} hint="лет в эксплуатации" />
        <StatCard label="Отказов" value={asset.failures_count ?? 0} accent={(asset.failures_count ?? 0) > 3 ? "danger" : "default"} />
        <StatCard label="Ремонтов" value={asset.repairs_count ?? 0} />
        <StatCard label="Дней без ТО" value={asset.days_since_maintenance?.toFixed(0) ?? "—"} />
        <StatCard label="Индекс состояния" value={asset.health_score?.toFixed(1) ?? "—"} accent={healthColor as any} hint="по цифровой копии" />
        <StatCard label="Риск отказа за 90 дней" value={
          asset.latest_risk_probability != null ?
            `${(asset.latest_risk_probability * 100).toFixed(1)}%` : "—"
        } hint={
            asset.previous_risk_probability != null &&
            asset.latest_risk_probability != null &&
            Math.abs(asset.previous_risk_probability - asset.latest_risk_probability) > 0.005
              ? (asset.latest_risk_probability < asset.previous_risk_probability
                  ? `↓ было ${(asset.previous_risk_probability * 100).toFixed(1)}%`
                  : `↑ было ${(asset.previous_risk_probability * 100).toFixed(1)}%`)
              : "прогноз на квартал"
          }
          accent={asset.latest_risk_level === "high" ? "danger" :
                  asset.latest_risk_level === "medium" ? "warning" : "success"} />
      </div>

      {/* Наглядная цепочка «высокий риск → ТО → низкий риск» — для защиты ВКР.
          Показываем, когда есть предыдущий риск и новый заметно ниже. */}
      {asset.previous_risk_probability != null &&
       asset.latest_risk_probability != null &&
       (asset.previous_risk_probability - asset.latest_risk_probability) > 0.05 && (
        <div className="card" style={{ borderLeft: "4px solid var(--success, #16a34a)", padding: "10px 14px", marginTop: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Проведено техническое обслуживание</div>
          <div style={{ fontSize: 14, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={{
              background: "#fee2e2", color: "#991b1b",
              borderRadius: 6, padding: "3px 10px", fontWeight: 600,
            }}>
              Было: {(asset.previous_risk_probability * 100).toFixed(1)}%
            </span>
            <span style={{ color: "#6b7280" }}>→ зафиксировано ТО →</span>
            <span style={{
              background: "#dcfce7", color: "#14532d",
              borderRadius: 6, padding: "3px 10px", fontWeight: 600,
            }}>
              Стало: {(asset.latest_risk_probability * 100).toFixed(1)}%
            </span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--muted, #555)", marginTop: 10, lineHeight: 1.55 }}>
            После фиксации ремонта обновились ключевые признаки объекта —
            давность последнего ТО стала {asset.days_since_maintenance?.toFixed(0) ?? "0"} дн.,
            число ремонтов выросло до {asset.repairs_count ?? "—"}.
            Модель машинного обучения пересчитала прогноз отказа на обновлённых
            данных и снизила оценку с
            {" "}{(asset.previous_risk_probability * 100).toFixed(1)}% до
            {" "}{(asset.latest_risk_probability * 100).toFixed(1)}% на горизонте 90 дней.
          </div>
        </div>
      )}

      {/* ── Изображение объекта ──────────────────────────────── */}
      <div className="card">
        <div className="row-between" style={{ marginBottom: 8 }}>
          <div className="card__title" style={{ margin: 0 }}>Изображение объекта</div>
          <div className="row" style={{ gap: 8 }}>
            <label className="btn btn--ghost btn--sm" style={{ cursor: "pointer" }}>
              {uploadingImg ? <><Spinner /> Загрузка...</> : (asset.image_url ? "🔄 Заменить" : "📷 Загрузить")}
              <input
                type="file"
                accept="image/png, image/jpeg, image/jpg, image/webp, image/gif"
                style={{ display: "none" }}
                disabled={uploadingImg}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUploadImage(f);
                  e.target.value = "";
                }}
              />
            </label>
            {asset.image_url && (
              <button className="btn btn--ghost btn--sm" onClick={onDeleteImage}>🗑 Удалить</button>
            )}
          </div>
        </div>
        {asset.image_url ? (
          <div style={{ textAlign: "center" }}>
            <img
              src={staticBaseUrl + asset.image_url}
              alt={asset.name}
              style={{
                maxWidth: "100%",
                maxHeight: 420,
                borderRadius: 8,
                border: "1px solid #e5e7eb",
                objectFit: "contain",
              }}
            />
          </div>
        ) : (
          <div className="empty">
            Изображение не загружено.<br />
            Поддерживаются форматы PNG, JPG, JPEG, WEBP, GIF.
          </div>
        )}
      </div>

      {/* ── Параметры объекта + цифровая копия ────────────────── */}
      <div className="grid-2">
        <div className="card">
          <div className="card__title">Параметры объекта</div>
          <table className="table">
            <tbody>
              <tr><th>Тип</th><td>{asset.asset_type?.name}</td></tr>
              <tr><th>Напряжение</th><td>{asset.voltage_class}</td></tr>
              <tr><th>Регион</th><td>{asset.region}</td></tr>
              <tr><th>Координаты</th><td>{asset.location_lat?.toFixed(4)}, {asset.location_lon?.toFixed(4)}</td></tr>
              <tr><th>Установлен</th><td>{asset.installed_date}</td></tr>
              <tr><th>Критичность</th><td>{(asset.criticality * 100).toFixed(0)}%</td></tr>
              <tr><th>Статус</th><td><span className={`badge badge--${asset.status}`}>{STATUS_LABEL[asset.status] || asset.status}</span></td></tr>
              <tr><th>Уровень риска</th><td><RiskBadge level={asset.latest_risk_level} probability={asset.latest_risk_probability} /></td></tr>
              <tr><th>Последний осмотр</th><td>{asset.latest_inspection_score ? `${asset.latest_inspection_score} / 5` : "—"}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="card__title">Цифровая копия — состояние узла</div>
          {twin ? (
            <>
              <div style={{ marginBottom: 12 }}>
                <div className="muted" style={{ fontSize: 12 }}>Индекс состояния</div>
                <div className="bar" style={{ marginTop: 6 }}>
                  <div className={`bar__fill bar__fill--${healthColor === "success" ? "green" : healthColor === "warning" ? "yellow" : "red"}`}
                       style={{ width: `${twin.health || 0}%` }} />
                </div>
                <div style={{ marginTop: 4, fontSize: 13 }}>
                  {twin.health?.toFixed(1)} / 100
                </div>
              </div>
              <table className="table">
                <tbody>
                  <tr><th>Категория</th><td>{CATEGORY_LABEL[twin.category] || twin.category}</td></tr>
                  <tr><th>Возраст</th><td>{twin.age?.toFixed(1)} лет</td></tr>
                  {/* Параметры, специфичные для категории объекта */}
                  {(CATEGORY_PARAMS[twin.category] || CATEGORY_PARAMS.transformer).map((p) => {
                    const val = twin[p.key];
                    if (val == null) return null;
                    const display = p.key === "age_ratio"
                      ? `${(val * 100).toFixed(0)}% от норматива`
                      : `${val.toFixed(1)}${p.suffix}`;
                    return <tr key={p.key}><th>{p.label}</th><td>{display}</td></tr>;
                  })}
                  <tr><th>Риск (цифр. копия)</th><td>{((twin.risk ?? 0) * 100).toFixed(1)}%</td></tr>
                  <tr>
                    <th>Зависимые объекты</th>
                    <td>
                      {twin.downstream_count} объектов могут пострадать при отказе
                      {twin.downstream_count > 0 && (
                        <div className="muted" style={{ fontSize: 12 }}>
                          IDs: {twin.downstream_ids?.join(", ") || "—"}
                        </div>
                      )}
                    </td>
                  </tr>
                </tbody>
              </table>

              {/* ── Разложение факторов индекса ─────────────────────── */}
              {twin.breakdown && Object.keys(twin.breakdown).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                    Вклад факторов в индекс состояния
                  </div>
                  {(() => {
                    const entries = Object.entries(twin.breakdown as Record<string, number>)
                      .filter(([, v]) => v !== 0)
                      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
                    const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 1);
                    return (
                      <table className="table" style={{ fontSize: 13 }}>
                        <tbody>
                          {entries.map(([k, v]) => {
                            const positive = v > 0;
                            const width = (Math.abs(v) / maxAbs) * 100;
                            return (
                              <tr key={k}>
                                <td style={{ width: "55%" }}>{FACTOR_LABEL[k] || k}</td>
                                <td style={{ width: 60, textAlign: "right", fontWeight: 600,
                                             color: positive ? "#15803d" : "#991b1b" }}>
                                  {positive ? "+" : ""}{v.toFixed(1)}
                                </td>
                                <td>
                                  <div style={{
                                    width: `${width}%`, height: 10, borderRadius: 5,
                                    background: positive ? "#86efac" : "#fca5a5",
                                  }} />
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    );
                  })()}
                </div>
              )}
            </>
          ) : (
            <div className="empty">
              Узел не загружен в граф.<br />
              Запустите перестроение через POST /api/twin/rebuild
            </div>
          )}
        </div>
      </div>

      {/* ── История осмотров ──────────────────────────────────── */}
      <div className="card">
        <div className="row-between" style={{ marginBottom: 8 }}>
          <div className="card__title" style={{ margin: 0 }}>История осмотров ({insp.length})</div>
          <button className="btn btn--primary btn--sm" onClick={() => setModal({ kind: "insp", initial: null })}>
            ➕ Добавить осмотр
          </button>
        </div>
        {insp.length === 0 ? <div className="empty">Осмотров нет.</div> : (
          <table className="table">
            <thead><tr><th>Дата</th><th>Оценка</th><th>Дефекты</th><th>Заметки</th><th></th></tr></thead>
            <tbody>
              {insp.slice(0, 10).map((i) => (
                <tr key={i.id}>
                  <td>{new Date(i.inspected_at).toLocaleDateString("ru-RU")}</td>
                  <td>{i.condition_score} / 5</td>
                  <td>{i.defects_found || "—"}</td>
                  <td>{i.notes || "—"}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <button className="btn btn--ghost btn--sm" title="Редактировать"
                              onClick={() => setModal({ kind: "insp", initial: i })}>✎</button>
                      <button className="btn btn--ghost btn--sm" title="Удалить"
                              onClick={() => onDeleteInsp(i)}>🗑</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── История ремонтов ──────────────────────────────────── */}
      <div className="card">
        <div className="row-between" style={{ marginBottom: 8 }}>
          <div className="card__title" style={{ margin: 0 }}>История ремонтов ({reps.length})</div>
          <button className="btn btn--primary btn--sm" onClick={() => setModal({ kind: "rep", initial: null })}>
            ➕ Добавить ремонт
          </button>
        </div>
        {reps.length === 0 ? <div className="empty">Ремонтов не было.</div> : (
          <table className="table">
            <thead><tr><th>Тип</th><th>Начало</th><th>Окончание</th><th>Стоимость, ₽</th><th>Описание</th><th></th></tr></thead>
            <tbody>
              {reps.slice(0, 10).map((r) => (
                <tr key={r.id}>
                  <td><span className="badge badge--info">{REPAIR_TYPE_LABEL[r.repair_type] || r.repair_type}</span></td>
                  <td>{r.started_at ? new Date(r.started_at).toLocaleDateString("ru-RU") : "—"}</td>
                  <td>{r.completed_at ? new Date(r.completed_at).toLocaleDateString("ru-RU") : "—"}</td>
                  <td>{r.cost ? Number(r.cost).toLocaleString("ru-RU") : "—"}</td>
                  <td>{r.work_description || "—"}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <button className="btn btn--ghost btn--sm" title="Редактировать"
                              onClick={() => setModal({ kind: "rep", initial: r })}>✎</button>
                      <button className="btn btn--ghost btn--sm" title="Удалить"
                              onClick={() => onDeleteRep(r)}>🗑</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── История отказов ───────────────────────────────────── */}
      <div className="card">
        <div className="row-between" style={{ marginBottom: 8 }}>
          <div className="card__title" style={{ margin: 0 }}>История отказов ({fails.length})</div>
          <button className="btn btn--primary btn--sm" onClick={() => setModal({ kind: "fail", initial: null })}>
            🚨 Зарегистрировать отказ
          </button>
        </div>
        {fails.length === 0 ? <div className="empty">Отказов нет.</div> : (
          <table className="table">
            <thead><tr><th>Дата</th><th>Тип</th><th>Тяжесть</th><th>Простой, ч</th><th>Причина</th><th></th></tr></thead>
            <tbody>
              {fails.slice(0, 10).map((f) => (
                <tr key={f.id}>
                  <td>{new Date(f.failed_at).toLocaleDateString("ru-RU")}</td>
                  <td>{f.failure_type || "—"}</td>
                  <td>
                    <span className={`badge ${
                      f.severity === "critical" ? "badge--high" :
                      f.severity === "major"    ? "badge--medium" : "badge--low"
                    }`}>
                      {SEVERITY_LABEL[f.severity] || f.severity}
                    </span>
                  </td>
                  <td>{f.downtime_hours?.toFixed(1) || "—"}</td>
                  <td>{f.root_cause || "—"}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <button className="btn btn--ghost btn--sm" title="Редактировать"
                              onClick={() => setModal({ kind: "fail", initial: f })}>✎</button>
                      <button className="btn btn--ghost btn--sm" title="Удалить"
                              onClick={() => onDeleteFail(f)}>🗑</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Модальные окна ─────────────────────────────────────── */}
      <Modal open={modal?.kind === "asset"} title={`Редактирование объекта #${asset.id}`}
             onClose={() => setModal(null)} width={720}>
        {modal?.kind === "asset" && (
          <AssetForm initial={asset} onCancel={() => setModal(null)} onDone={closeReload} />
        )}
      </Modal>

      <Modal open={modal?.kind === "insp"}
             title={modal?.kind === "insp" && modal.initial ? "Редактирование осмотра" : "Новый осмотр"}
             onClose={() => setModal(null)} width={560}>
        {modal?.kind === "insp" && (
          <InspectionForm assetId={assetId} initial={modal.initial}
                          onCancel={() => setModal(null)} onDone={closeReload} />
        )}
      </Modal>

      <Modal open={modal?.kind === "rep"}
             title={modal?.kind === "rep" && modal.initial ? "Редактирование ремонта" : "Новый ремонт"}
             onClose={() => setModal(null)} width={640}>
        {modal?.kind === "rep" && (
          <RepairForm assetId={assetId} initial={modal.initial}
                      onCancel={() => setModal(null)} onDone={closeReload} />
        )}
      </Modal>

      <Modal open={modal?.kind === "fail"}
             title={modal?.kind === "fail" && modal.initial ? "Редактирование отказа" : "Регистрация отказа"}
             onClose={() => setModal(null)} width={640}>
        {modal?.kind === "fail" && (
          <FailureForm assetId={assetId} initial={modal.initial}
                       onCancel={() => setModal(null)} onDone={closeReload} />
        )}
      </Modal>
    </div>
  );
}
