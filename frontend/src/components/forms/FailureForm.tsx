// FailureForm.tsx — форма регистрации и редактирования отказа оборудования.

import { useState } from "react";
import { addFailure, updateFailure } from "../../api/client";
import type { Failure } from "../../types";
import { Spinner } from "../Loading";

interface Props {
  assetId: number;
  initial?: Failure | null;
  onDone: () => void;
  onCancel: () => void;
}

const SEVERITIES = [
  { v: "minor", l: "Незначительная" },
  { v: "major", l: "Серьёзная" },
  { v: "critical", l: "Критическая" },
];

const FAILURE_TYPES = [
  "Пробой изоляции",
  "Механическое повреждение",
  "Перегрев",
  "Короткое замыкание",
  "Износ контактов",
];

const ROOT_CAUSES = [
  "Износ оборудования",
  "Атмосферные воздействия",
  "Перегрузка",
  "Механическое воздействие",
  "Производственный дефект",
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

export default function FailureForm({ assetId, initial, onDone, onCancel }: Props) {
  const isEdit = !!initial;
  const [failedAt, setFailedAt] = useState(toLocalInputValue(initial?.failed_at));
  const [severity, setSeverity] = useState(initial?.severity ?? "minor");
  const [type, setType] = useState(initial?.failure_type ?? FAILURE_TYPES[0]);
  const [downtime, setDowntime] = useState<string>(initial?.downtime_hours?.toString() ?? "");
  const [cause, setCause] = useState(initial?.root_cause ?? ROOT_CAUSES[0]);
  const [resolvedAt, setResolvedAt] = useState(initial?.resolved_at ? toLocalInputValue(initial.resolved_at) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (resolvedAt && new Date(resolvedAt) < new Date(failedAt)) {
      return setErr("Время устранения не может быть раньше времени отказа");
    }
    setBusy(true);
    try {
      const body: any = {
        failed_at: new Date(failedAt).toISOString(),
        severity,
        failure_type: type || null,
        downtime_hours: downtime ? Number(downtime) : null,
        root_cause: cause || null,
        resolved_at: resolvedAt ? new Date(resolvedAt).toISOString() : null,
      };
      if (isEdit && initial) {
        await updateFailure(initial.id, body);
      } else {
        body.asset_id = assetId;
        await addFailure(body);
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
          <label>Время отказа*</label>
          <input className="input" type="datetime-local" value={failedAt}
                 onChange={(e) => setFailedAt(e.target.value)} required />
        </div>

        <div className="form__row">
          <label>Время устранения</label>
          <input className="input" type="datetime-local" value={resolvedAt}
                 onChange={(e) => setResolvedAt(e.target.value)} />
        </div>

        <div className="form__row">
          <label>Тяжесть*</label>
          <select className="select" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
          </select>
        </div>

        <div className="form__row">
          <label>Простой, ч</label>
          <input className="input" type="number" min={0} step={0.5} value={downtime}
                 onChange={(e) => setDowntime(e.target.value)} placeholder="например, 12" />
        </div>

        <div className="form__row">
          <label>Тип отказа</label>
          {/* select со списком + ввод произвольного значения через list */}
          <input className="input" list="ft-list" value={type} onChange={(e) => setType(e.target.value)} />
          <datalist id="ft-list">
            {FAILURE_TYPES.map((t) => <option key={t} value={t} />)}
          </datalist>
        </div>

        <div className="form__row">
          <label>Корневая причина</label>
          <input className="input" list="rc-list" value={cause} onChange={(e) => setCause(e.target.value)} />
          <datalist id="rc-list">
            {ROOT_CAUSES.map((c) => <option key={c} value={c} />)}
          </datalist>
        </div>
      </div>

      {err && <div className="error" style={{ marginTop: 8 }}>{err}</div>}

      <div className="form__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>Отмена</button>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? <><Spinner /> Сохранение...</> : (isEdit ? "💾 Сохранить" : "🚨 Зарегистрировать отказ")}
        </button>
      </div>
    </form>
  );
}
