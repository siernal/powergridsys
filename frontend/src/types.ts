// types.ts — TypeScript-интерфейсы, соответствующие Pydantic-схемам бэкенда.
// Изменения в schemas.py должны отражаться здесь.

/** Тип оборудования из справочника (трансформатор, линия и т.д.) */
export interface AssetType {
  id: number;
  name: string;
  category: "transformer" | "line" | "substation" | "cable" | string;
  base_lifetime_years?: number;   // нормативный срок службы, лет
  criticality_default?: number;   // базовая критичность 0..1
}

/** Объект электросети (трансформатор, линия, подстанция, кабель) */
export interface Asset {
  id: number;
  name: string;
  asset_type_id: number;
  asset_type?: AssetType | null;      // вложенный тип (если запрошен через JOIN)
  location_lat?: number | null;       // широта WGS-84
  location_lon?: number | null;       // долгота WGS-84
  region?: string | null;             // Северный / Южный / Восточный / Западный / Центральный
  installed_date?: string | null;     // ISO дата: «2010-03-15»
  voltage_class?: string | null;      // «10кВ» / «35кВ» / «110кВ» / «0.4кВ»
  criticality: number;                // итоговая критичность 0..1
  status: "active" | "maintenance" | "failed" | "decommissioned" | string;
  image_url?: string | null;          // относительный путь к изображению объекта (/static/assets/…)
  created_at: string;
}

/** Расширенная карточка объекта — используется на странице AssetDetail */
export interface AssetDetail extends Asset {
  age_years?: number | null;                  // лет в эксплуатации (вычисляется)
  failures_count?: number | null;             // всего зафиксированных отказов
  repairs_count?: number | null;              // всего ремонтов
  latest_inspection_score?: number | null;    // последняя оценка осмотра 1..5
  days_since_maintenance?: number | null;     // дней без ТО
  latest_risk_probability?: number | null;    // последняя вероятность отказа 0..1
  latest_risk_level?: "low" | "medium" | "high" | string | null;
  health_score?: number | null;               // балл здоровья из digital twin 0..100
}

/** Запись об осмотре объекта */
export interface Inspection {
  id: number;
  asset_id: number;
  inspected_at: string;         // ISO datetime
  condition_score: number;      // оценка 1..5 (1=аварийное, 5=отличное)
  defects_found?: string | null;
  notes?: string | null;
  created_at: string;
}

/** Запись о ремонте или ТО */
export interface Repair {
  id: number;
  asset_id: number;
  repair_type: string;          // «planned» / «emergency» / «capital»
  started_at?: string | null;
  completed_at?: string | null;
  cost?: number | null;         // стоимость, руб.
  work_description?: string | null;
  performed_by?: string | null; // «Бригада №3»
}

/** Запись об отказе оборудования */
export interface Failure {
  id: number;
  asset_id: number;
  failed_at: string;
  failure_type?: string | null;     // «Пробой изоляции», «КЗ» и т.п.
  severity: string;                 // «minor» / «major» / «critical»
  downtime_hours?: number | null;   // часов простоя
  root_cause?: string | null;       // корневая причина
  resolved_at?: string | null;      // время устранения
}

/** Результат расчёта риска ML-моделью */
export interface RiskScore {
  id: number;
  asset_id: number;
  calculated_at: string;
  risk_probability: number;     // вероятность отказа 0..1
  risk_level: "low" | "medium" | "high" | string;
  feature_snapshot?: Record<string, unknown> | null;  // снимок признаков для объяснимости
  model_version?: string | null;
}

/** Запись плана технического обслуживания */
export interface MaintenancePlan {
  id: number;
  asset_id: number;
  asset_name?: string | null;           // имя объекта (подставляется бэкендом)
  plan_date: string;                    // ISO дата: «2025-08-12»
  priority?: number | null;            // порядковый номер приоритета
  maintenance_type?: string | null;    // «emergency_inspection» / «planned_maintenance» / «routine_inspection»
  estimated_duration_h?: number | null; // оценочная длительность, ч
  estimated_cost?: number | null;       // оценочная стоимость, руб.
  status: string;                       // «scheduled» / «completed» / «cancelled»
  notes?: string | null;               // заметки с деталями расчёта приоритета
  auto_generated: boolean;             // true = создано алгоритмом
}

/** Сводные KPI для главного дашборда */
export interface AnalyticsSummary {
  total_assets: number;              // всего объектов на балансе
  active: number;
  in_maintenance: number;
  failed: number;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  total_failures_last_year: number;  // отказов за 365 дней
  total_repairs_last_year: number;
  avg_health_score: number | null;   // средний health из digital twin
  upcoming_maintenance_count: number; // запланировано на ближайшие 30 дней
}

/** Объект с риском — используется и в топ-N (дашборд) и в полной таблице (прогноз) */
export interface TopRiskAsset {
  asset_id: number;
  asset_name: string;
  region: string;
  risk_prob: number | null;    // вероятность отказа 0..1; null если риск не рассчитан
  risk_level: string | null;   // «high» / «medium» / «low»; null если риск не рассчитан
  criticality: number;         // критичность 0..1
}

/** Метрики качества ML-модели (отображаются на странице «Прогноз отказов») */
export interface ModelMetrics {
  roc_auc?: number;              // ROC-AUC на тестовой выборке
  f1_macro?: number;             // F1-macro на тестовой выборке
  n_train?: number;              // размер обучающей выборки
  n_test?: number;               // размер тестовой выборки
  positive_rate?: number;        // доля положительных примеров
  feature_columns?: string[];    // список признаков (отображаются как бейджи)
  model_version?: string;        // версия модели (например «2.0»)
  trained_at?: string;           // ISO datetime момента обучения
}
