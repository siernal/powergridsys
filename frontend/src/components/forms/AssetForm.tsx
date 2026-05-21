// AssetForm.tsx — форма создания и редактирования объекта электросети.
// Универсальная: если передан initial — режим редактирования (PUT),
// иначе создание (POST). Список типов загружается из API один раз.

import { useEffect, useState } from "react";
import { listAssetTypes, createAsset, updateAsset } from "../../api/client";
import type { Asset } from "../../types";
import { Spinner } from "../Loading";

interface Props {
  initial?: Asset | null;          // если задан — режим редактирования
  onDone: () => void;              // вызывается после успешного сохранения
  onCancel: () => void;
}

const REGIONS = ["Северный", "Южный", "Восточный", "Западный", "Центральный"];
const VOLTAGES = ["0.4кВ", "10кВ", "35кВ", "110кВ"];
const STATUSES = [
  { v: "active", l: "Активен" },
  { v: "maintenance", l: "В ремонте" },
  { v: "failed", l: "Авария" },
  { v: "decommissioned", l: "Списан" },
];

export default function AssetForm({ initial, onDone, onCancel }: Props) {
  const isEdit = !!initial;
  // Локальное состояние формы — инициализируется из initial или дефолтами
  const [name, setName] = useState(initial?.name ?? "");
  const [typeId, setTypeId] = useState<number>(initial?.asset_type_id ?? 0);
  const [region, setRegion] = useState(initial?.region ?? "");
  const [voltage, setVoltage] = useState(initial?.voltage_class ?? "");
  const [installed, setInstalled] = useState(initial?.installed_date ?? "");
  const [crit, setCrit] = useState<number>(initial?.criticality ?? 0.5);
  const [status, setStatus] = useState(initial?.status ?? "active");
  const [lat, setLat] = useState<string>(initial?.location_lat?.toString() ?? "");
  const [lon, setLon] = useState<string>(initial?.location_lon?.toString() ?? "");

  const [types, setTypes] = useState<{ id: number; name: string; category: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Загружаем справочник типов при монтировании
  useEffect(() => {
    listAssetTypes().then((t) => {
      setTypes(t);
      // При создании ставим первый тип по умолчанию
      if (!isEdit && t.length && !typeId) setTypeId(t[0].id);
    });
    // eslint-disable-next-line
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    // Минимальная клиентская валидация
    if (!name.trim()) return setErr("Укажите наименование");
    if (!typeId) return setErr("Выберите тип оборудования");
    if (!installed) return setErr("Укажите дату ввода в эксплуатацию");

    const body: any = {
      name: name.trim(),
      asset_type_id: typeId,
      region: region || null,
      voltage_class: voltage || null,
      installed_date: installed,
      criticality: crit,
      status,
      location_lat: lat ? Number(lat) : null,
      location_lon: lon ? Number(lon) : null,
    };

    setBusy(true);
    try {
      if (isEdit && initial) await updateAsset(initial.id, body);
      else await createAsset(body);
      onDone();
    } catch (e: any) {
      // FastAPI вернёт detail в теле ответа
      setErr(e?.response?.data?.detail || e?.message || "Ошибка сохранения");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="form">
      <div className="form__row">
        <label>Наименование*</label>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>

      <div className="form__grid">
        <div className="form__row">
          <label>Тип оборудования*</label>
          <select className="select" value={typeId} onChange={(e) => setTypeId(+e.target.value)} required>
            <option value={0}>— выберите —</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>

        <div className="form__row">
          <label>Класс напряжения</label>
          <select className="select" value={voltage} onChange={(e) => setVoltage(e.target.value)}>
            <option value="">—</option>
            {VOLTAGES.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>

        <div className="form__row">
          <label>Регион</label>
          <select className="select" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">—</option>
            {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        <div className="form__row">
          <label>Статус</label>
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
          </select>
        </div>

        <div className="form__row">
          <label>Дата ввода в эксплуатацию*</label>
          <input className="input" type="date" value={installed} onChange={(e) => setInstalled(e.target.value)} required />
        </div>

        <div className="form__row">
          <label>Критичность (0–1)</label>
          {/* range + текстовое отображение значения справа */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input className="input" type="range" min={0} max={1} step={0.05}
                   value={crit} onChange={(e) => setCrit(+e.target.value)} style={{ flex: 1 }} />
            <span style={{ minWidth: 48, textAlign: "right" }}>{(crit * 100).toFixed(0)}%</span>
          </div>
        </div>

        <div className="form__row">
          <label>Широта (WGS-84)</label>
          <input className="input" type="number" step="0.000001" value={lat}
                 onChange={(e) => setLat(e.target.value)} placeholder="например, 55.751244" />
        </div>

        <div className="form__row">
          <label>Долгота (WGS-84)</label>
          <input className="input" type="number" step="0.000001" value={lon}
                 onChange={(e) => setLon(e.target.value)} placeholder="например, 37.618423" />
        </div>
      </div>

      {err && <div className="error" style={{ marginTop: 8 }}>{err}</div>}

      <div className="form__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>Отмена</button>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? <><Spinner /> Сохранение...</> : (isEdit ? "💾 Сохранить" : "➕ Создать")}
        </button>
      </div>
    </form>
  );
}
