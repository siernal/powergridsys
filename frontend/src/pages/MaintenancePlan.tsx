// MaintenancePlan.tsx — страница планирования ТОиР.
// Генерация плана: maintenance_planner.py считает приоритет каждого объекта
//   по формуле 0.5·risk + 0.3·crit + 0.2·(dsm/365)^(1/3), лимит 5 работ/день.
// В поле notes записывается: "Риск: 75.0%, Приоритет: 0.875, Без ТО 123 дней".
// parseNotes() разбирает эту строку и отображает данные как цветные бейджи.

import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  generateMaintenancePlan, listPlans,
} from "../api/client";
import type { MaintenancePlan } from "../types";
import { Loading, Spinner } from "../components/Loading";
import Modal from "../components/Modal";
import RepairForm from "../components/forms/RepairForm";

const TYPE_LABEL: Record<string, string> = {
  emergency_inspection: "Срочный осмотр",
  planned_maintenance:  "Плановое ТО",
  routine_inspection:   "Регламентный осмотр",
};

const TYPE_BADGE: Record<string, string> = {
  emergency_inspection: "badge--high",
  planned_maintenance:  "badge--medium",
  routine_inspection:   "badge--low",
};

// Разбор строки notes вида "Риск: 75.0%, Приоритет: 0.875, Без ТО 123 дней"
function parseNotes(notes: string | null | undefined) {
  if (!notes) return null;
  const riskMatch    = notes.match(/Риск:\s*([\d.]+)%/);
  const dsmMatch     = notes.match(/Без ТО\s*(\d+)\s*дн/);
  const riskPct      = riskMatch  ? parseFloat(riskMatch[1])  : null;
  const dsmDays      = dsmMatch   ? parseInt(dsmMatch[1], 10) : null;
  return { riskPct, dsmDays };
}

// Цвет и метка для риска по порогам maintenance_planner.py: ≥60% высокий, ≥30% средний
function riskStyle(pct: number) {
  if (pct >= 60) return { color: "#991b1b", bg: "#fee2e2", label: "Высокий" };
  if (pct >= 30) return { color: "#92400e", bg: "#fef3c7", label: "Средний" };
  return           { color: "#14532d", bg: "#dcfce7", label: "Низкий" };
}

export default function MaintenancePlanPage() {
  const [plans, setPlans] = useState<MaintenancePlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(90);

  const load = () => {
    setLoading(true);
    // Загружаем все статусы — и scheduled, и completed.
    // Выполненные записи остаются видимыми с пометкой «ТО проведено»,
    // чтобы для защиты была наглядна связь риск → ТО → закрытие пункта плана.
    listPlans()
      .then(setPlans)
      .catch((e) => setErr(e?.message || "Ошибка"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const onGenerate = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await generateMaintenancePlan(horizon);
      setMsg(`✅ Сгенерировано работ: ${r.generated}`);
      load();
    } catch (e: any) { setMsg(`❌ ${e?.message || "Ошибка"}`); }
    finally { setBusy(false); }
  };

  // Какой объект сейчас редактируется через модалку «Зафиксировать ТО».
  // null = модалка закрыта; число = asset_id.
  const [repairFor, setRepairFor] = useState<{ id: number; name: string } | null>(null);

  // Клик «Выполнено» в строке плана — открывает форму создания записи о ремонте/ТО.
  // После сохранения записи бэкенд (хук _close_matching_plan) сам переведёт
  // соответствующую плановую запись в status='completed', а риск-скор для
  // объекта пересчитается через _recalculate_risk_for_asset.
  const onComplete = (plan: MaintenancePlan) => {
    setRepairFor({
      id: plan.asset_id,
      name: plan.asset_name || `№${plan.asset_id}`,
    });
  };
  const onRepairSaved = () => {
    setRepairFor(null);
    load();
  };

  // Тумблер «Показать выполненные»: по умолчанию выкл — completed скрыты.
  const [showCompleted, setShowCompleted] = useState(false);

  // Только запланированные работы участвуют в подсчёте человекочасов и стоимости.
  const activePlans = plans.filter((p) => (p.status || "scheduled") === "scheduled");

  // Что реально показываем в таблице — фильтр срабатывает мгновенно через useMemo,
  // без обращения к серверу.
  const visiblePlans = useMemo(
    () => (showCompleted ? plans : activePlans),
    [plans, activePlans, showCompleted],
  );
  const completedCount = plans.length - activePlans.length;
  const totalCost   = activePlans.reduce((s, p) => s + (p.estimated_cost || 0), 0);
  const totalH      = activePlans.reduce((s, p) => s + (p.estimated_duration_h || 0), 0);

  // Когда был последний раз сгенерирован план — берём максимальный created_at
  // среди запланированных (auto_generated) записей.
  // ВАЖНО: бэкенд хранит время в UTC без TZ-суффикса. Без явного "Z" браузер
  // парсит строку как локальное время и сдвига на нужный часовой пояс не происходит.
  const parseUtc = (s: string) =>
    new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : s + "Z");

  const lastGeneratedAt = useMemo(() => {
    const dates = activePlans
      .filter((p) => p.auto_generated && p.created_at)
      .map((p) => parseUtc(p.created_at as string).getTime());
    if (!dates.length) return null;
    return new Date(Math.max(...dates));
  }, [activePlans]);

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 16 }}>
        <h1>План ТОиР</h1>
        <span className="muted">
          {activePlans.length} запланированных
          {plans.length - activePlans.length > 0 && (
            <> · {plans.length - activePlans.length} выполненных</>
          )}
        </span>
      </div>

      {/* ── Плашка: когда план был сгенерирован ──────────────────── */}
      {lastGeneratedAt && (
        <div className="card" style={{
          marginBottom: 16,
          borderLeft: "4px solid #2563eb",
          padding: "10px 14px",
          display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
        }}>
          <span style={{ fontSize: 18 }}>📅</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>
              План сгенерирован: {lastGeneratedAt.toLocaleString("ru-RU", {
                day: "2-digit", month: "long", year: "numeric",
                hour: "2-digit", minute: "2-digit",
                timeZone: "Asia/Yekaterinburg",
              })} (Екб)
            </div>
            <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
              Риски в колонке «Основание» зафиксированы на момент генерации.
            </div>
          </div>
        </div>
      )}

      {/* ── Плашка: правила определения уровня риска ─────────────── */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card__title">Критерии уровня риска</div>
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "#fee2e2", borderRadius: 8, padding: "8px 14px",
            border: "1px solid #fca5a5",
          }}>
            <span style={{ fontSize: 18 }}>🔴</span>
            <div>
              <div style={{ fontWeight: 600, color: "#991b1b", fontSize: 13 }}>Высокий риск ≥ 60%</div>
              <div style={{ fontSize: 12, color: "#7f1d1d" }}>
                Срочный осмотр в течение 30 дней
              </div>
            </div>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "#fef3c7", borderRadius: 8, padding: "8px 14px",
            border: "1px solid #fcd34d",
          }}>
            <span style={{ fontSize: 18 }}>🟡</span>
            <div>
              <div style={{ fontWeight: 600, color: "#92400e", fontSize: 13 }}>Средний риск 30–60%</div>
              <div style={{ fontSize: 12, color: "#78350f" }}>
                Плановое ТО в течение 90 дней
              </div>
            </div>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "#dcfce7", borderRadius: 8, padding: "8px 14px",
            border: "1px solid #86efac",
          }}>
            <span style={{ fontSize: 18 }}>🟢</span>
            <div>
              <div style={{ fontWeight: 600, color: "#14532d", fontSize: 13 }}>Низкий риск &lt; 30%</div>
              <div style={{ fontSize: 12, color: "#166534" }}>
                Регламентный осмотр в течение 180 дней
              </div>
            </div>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "#f3f4f6", borderRadius: 8, padding: "8px 14px",
            border: "1px solid #d1d5db", marginLeft: "auto",
          }}>
            <div style={{ fontSize: 12, color: "#374151", lineHeight: 1.5 }}>
              <strong>Приоритет</strong> = 0.5 · риск + 0.3 · критичность + 0.2 · срок<br />
              Лимит: не более 5 работ в день
            </div>
          </div>
        </div>
      </div>

      {/* ── Панель генерации плана ───────────────────────────────── */}
      <div className="card">
        <div className="card__title">Генерация плана</div>
        <div className="row">
          <label>
            Горизонт планирования:
            <select className="select" style={{ marginLeft: 8 }}
                    value={horizon} onChange={(e) => setHorizon(+e.target.value)}>
              <option value={30}>30 дней</option>
              <option value={90}>90 дней</option>
              <option value={180}>180 дней</option>
              <option value={365}>1 год</option>
            </select>
          </label>
          <button className="btn btn--primary" onClick={onGenerate} disabled={busy}>
            {busy ? <><Spinner /> Генерация...</> : "🛠️ Сгенерировать план"}
          </button>
        </div>
        {msg && <div style={{ marginTop: 12, fontSize: 13 }}>{msg}</div>}
      </div>

      {/* ── Сводные KPI плана ────────────────────────────────────── */}
      <div className="stat-grid">
        <div className="stat">
          <div className="stat__label">Всего работ</div>
          <div className="stat__value">{plans.length}</div>
        </div>
        <div className="stat">
          <div className="stat__label">Суммарно человекочасов</div>
          <div className="stat__value">{totalH.toFixed(0)}</div>
        </div>
        <div className="stat">
          <div className="stat__label">Оценка стоимости, ₽</div>
          <div className="stat__value">{totalCost.toLocaleString("ru-RU")}</div>
        </div>
      </div>

      {/* ── Тумблер «Показать выполненные» — переключает мгновенно ───── */}
      {!loading && !err && completedCount > 0 && (
        <div className="row-between" style={{ margin: "12px 4px 8px" }}>
          <span className="muted" style={{ fontSize: 13 }}>
            {showCompleted
              ? `Показаны все ${plans.length} записей (${completedCount} выполненных)`
              : `${activePlans.length} активных записей · ${completedCount} выполненных скрыто`}
          </span>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13 }}>
            <input type="checkbox" checked={showCompleted}
                   onChange={(e) => setShowCompleted(e.target.checked)} />
            Показать выполненные
          </label>
        </div>
      )}

      {/* ── Таблица запланированных работ ────────────────────────── */}
      {loading ? <Loading /> :
       err ? <div className="error">{err}</div> :
       visiblePlans.length === 0 ? (
        <div className="card empty">
          {plans.length === 0
            ? <>План пуст. Нажмите «Сгенерировать план» выше.<br />
              Перед этим лучше <Link to="/risk">рассчитать риски</Link>.</>
            : <>Активных работ нет — все плановые задачи выполнены.<br />
              Включите «Показать выполненные», чтобы увидеть историю.</>
          }
        </div>
       ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>Приор.</th>
                <th>Объект</th>
                <th>Тип работ</th>
                <th>Длит., ч</th>
                <th>Стоимость, ₽</th>
                <th>Основание</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visiblePlans.map((p) => {
                const parsed = parseNotes(p.notes);
                const rs = parsed?.riskPct != null ? riskStyle(parsed.riskPct) : null;
                const isDone = (p.status || "scheduled") !== "scheduled";
                return (
                  <tr key={p.id}
                      style={
                        isDone
                          ? { background: "#f3f4f6", color: "#9ca3af",
                              textDecoration: "line-through", opacity: 0.85 }
                          : rs ? { background: rs.bg + "66" } : undefined
                      }>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {new Date(p.plan_date).toLocaleDateString("ru-RU", {
                        day: "2-digit", month: "short", year: "numeric"
                      })}
                    </td>
                    <td>#{p.priority}</td>
                    <td><Link to={`/assets/${p.asset_id}`}>{p.asset_name || `#${p.asset_id}`}</Link></td>
                    <td>
                      <span className={`badge ${TYPE_BADGE[p.maintenance_type || ""] || "badge--neutral"}`}>
                        {TYPE_LABEL[p.maintenance_type || ""] || p.maintenance_type}
                      </span>
                    </td>
                    <td>{p.estimated_duration_h}</td>
                    <td>{p.estimated_cost ? Number(p.estimated_cost).toLocaleString("ru-RU") : "—"}</td>

                    {/* Колонка «Основание» — цветной бейдж риска + срок без ТО */}
                    <td>
                      {parsed ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {parsed.riskPct != null && rs && (
                            <span style={{
                              display: "inline-flex", alignItems: "center", gap: 4,
                              background: rs.bg, color: rs.color,
                              borderRadius: 6, padding: "2px 8px",
                              fontWeight: 600, fontSize: 12, width: "fit-content",
                            }}>
                              ⚠ Риск {parsed.riskPct.toFixed(1)}% — {rs.label}
                            </span>
                          )}
                          {parsed.dsmDays != null && (
                            <span style={{ fontSize: 11, color: "#6b7280" }}>
                              🕐 Без ТО {parsed.dsmDays} дн.
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="muted" style={{ fontSize: 12 }}>{p.notes || "—"}</span>
                      )}
                    </td>

                    <td>
                      {isDone ? (
                        <span style={{
                          display: "inline-flex", alignItems: "center", gap: 4,
                          background: "#dcfce7", color: "#14532d",
                          borderRadius: 6, padding: "2px 8px",
                          fontWeight: 600, fontSize: 12,
                          textDecoration: "none",
                        }}>
                          ✓ ТО проведено
                        </span>
                      ) : (
                        <button className="btn btn--ghost btn--sm" onClick={() => onComplete(p)}>
                          ✓ Выполнено
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
       )}

      {/* Модалка фиксации факта проведённого ТО прямо со страницы плана.
          Сохранение записи Repair → бэкенд автоматически закроет
          соответствующую плановую запись и пересчитает риск объекта. */}
      <Modal open={repairFor !== null}
             title={repairFor ? `Зафиксировать ТО — ${repairFor.name}` : ""}
             onClose={() => setRepairFor(null)} width={640}>
        {repairFor && (
          <RepairForm assetId={repairFor.id} initial={null}
                      onCancel={() => setRepairFor(null)} onDone={onRepairSaved} />
        )}
      </Modal>
    </div>
  );
}
