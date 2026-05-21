// RepairForm.tsx — форма создания и редактирования записи ремонта/ТО.

import { useState } from "react";
import { addRepair, updateRepair } from "../../api/client";
import type { Repair } from "../../types";
import { Spinner } from "../Loading";

interface Props {
  assetId: number;
  initial?: Repair | null;
  onDone: () => void;
  onCancel: () => void;
}

const REPAIR_TYPES = [
  { v: "planned", l: "Плановый" },
  { v: "emergency", l: "Аварийный" },
  { v: "capital", l: "Капитальный" },
];

function toLocalInputValue(iso?: string | null): string {
  if (!iso) {
    const d = new Date();
    d.setSeconds(0, 0);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function RepairForm({ assetId, initial, onDone, onCancel }: Props) {
  const isEdit = !!initial;
  const [repairType, setRepairType] = useState(initial?.repair_type ?? "planned");
  const [startedAt, setStartedAt] = useState(toLocalInputValue(initial?.started_at));
  // completed может быть пустым — ремонт ещё не завершён
  const [completedAt, setCompletedAt] = useState(initial?.completed_at ? toLocalInputValue(initial.completed_at) : "");
  const [cost, setCost] = useState<string>(initial?.cost?.toString() ?? "");
  const [desc, setDesc] = useState(initial?.work_description ?? "");
  const [team, setTeam] = useState(initial?.performed_by ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (!startedAt) return setErr("Укажите дату начала работ");
    // Если окончание задано, проверяем что оно после начала
    if (completedAt && new Date(completedAt) < new Date(startedAt)) {
      return setErr("Дата окончания не может быть раньше даты начала");
    }
    setBusy(true);
    try {
      const body: any = {
        repair_type: repairType,
        started_at: new Date(startedAt).toISOString(),
        completed_at: completedAt ? new Date(completedAt).toISOString() : null,
        cost: cost ? Number(cost) : null,
        work_description: desc || null,
        performed_by: team || null,
      };
      if (isEdit && initial) {
        await updateRepair(initial.id, body);
      } else {
        body.asset_id = assetId;
        await addRepair(body);
      }
      onDone();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Ошибка сохранения");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="form">
      <div className="form__grid">
        <div className="form__row">
          <label>Тип работ*</label>
          <select className="select" value={repairType} onChange={(e) => setRepairType(e.target.value)}>
            {REPAIR_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
          </select>
        </div>

        <div className="form__row">
          <label>Стоимость, ₽</label>
          <input className="input" type="number" min={0} step={100} value={cost}
                 onChange={(e) => setCost(e.target.value)} placeholder="например, 75000" />
        </div>

        <div className="form__row">
          <label>Начало работ*</label>
          <input className="input" type="datetime-local" value={startedAt}
                 onChange={(e) => setStartedAt(e.target.value)} required />
        </div>

        <div className="form__row">
          <label>Окончание работ</label>
          <input className="input" type="datetime-local" value={completedAt}
                 onChange={(e) => setCompletedAt(e.target.value)} />
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            Оставьте пустым, если ремонт ещё в процессе
          </div>
        </div>

        <div className="form__row">
          <label>Исполнитель</label>
          <input className="input" value={team} onChange={(e) => setTeam(e.target.value)}
                 placeholder="например, Бригада №3" />
        </div>
      </div>

      <div className="form__row">
        <label>Описание работ</label>
        <textarea className="input" rows={3} value={desc} onChange={(e) => setDesc(e.target.value)}
                  placeholder="Замена изоляторов, диагностика обмоток и т. д." />
      </div>

      {err && <div className="error" style={{ marginTop: 8 }}>{err}</div>}

      <div className="form__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>Отмена</button>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? <><Spinner /> Сохранение...</> : (isEdit ? "💾 Сохранить" : "➕ Добавить ремонт")}
        </button>
      </div>
    </form>
  );
}
