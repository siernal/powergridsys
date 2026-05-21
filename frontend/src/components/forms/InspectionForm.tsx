// InspectionForm.tsx — форма создания и редактирования записи осмотра.
// При создании передаётся assetId. При редактировании — initial.

import { useState } from "react";
import { addInspection, updateInspection } from "../../api/client";
import type { Inspection } from "../../types";
import { Spinner } from "../Loading";

interface Props {
  assetId: number;
  initial?: Inspection | null;
  onDone: () => void;
  onCancel: () => void;
}

// datetime-local требует формат YYYY-MM-DDTHH:mm
function toLocalInputValue(iso?: string | null): string {
  if (!iso) {
    const d = new Date();
    d.setSeconds(0, 0);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function InspectionForm({ assetId, initial, onDone, onCancel }: Props) {
  const isEdit = !!initial;
  const [when, setWhen] = useState(toLocalInputValue(initial?.inspected_at));
  const [score, setScore] = useState<number>(initial?.condition_score ?? 4);
  const [defects, setDefects] = useState(initial?.defects_found ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (score < 1 || score > 5) return setErr("Оценка состояния должна быть от 1 до 5");
    setBusy(true);
    try {
      // Сервер ожидает ISO с секундами — добавляем :00 к datetime-local
      const inspectedAt = new Date(when).toISOString();
      if (isEdit && initial) {
        await updateInspection(initial.id, {
          inspected_at: inspectedAt,
          condition_score: score,
          defects_found: defects || undefined,
          notes: notes || undefined,
        } as any);
      } else {
        await addInspection({
          asset_id: assetId,
          inspected_at: inspectedAt,
          condition_score: score,
          defects_found: defects || undefined,
          notes: notes || undefined,
        });
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
          <label>Дата и время осмотра*</label>
          <input className="input" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
        </div>

        <div className="form__row">
          <label>Оценка состояния (1–5)*</label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input className="input" type="range" min={1} max={5} step={1}
                   value={score} onChange={(e) => setScore(+e.target.value)} style={{ flex: 1 }} />
            <span style={{ minWidth: 40, textAlign: "right", fontWeight: 600 }}>{score} / 5</span>
          </div>
          {/* Подсказка по шкале */}
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            1 — аварийное, 3 — удовлетворительное, 5 — отличное
          </div>
        </div>
      </div>

      <div className="form__row">
        <label>Выявленные дефекты</label>
        <textarea className="input" rows={2} value={defects} onChange={(e) => setDefects(e.target.value)}
                  placeholder="Например: трещины на изоляторах" />
      </div>

      <div className="form__row">
        <label>Заметки</label>
        <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="Произвольный комментарий" />
      </div>

      {err && <div className="error" style={{ marginTop: 8 }}>{err}</div>}

      <div className="form__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>Отмена</button>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? <><Spinner /> Сохранение...</> : (isEdit ? "💾 Сохранить" : "➕ Добавить осмотр")}
        </button>
      </div>
    </form>
  );
}
