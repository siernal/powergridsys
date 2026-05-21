// api/client.ts — HTTP-клиент для всех запросов к бэкенду.
// Использует axios. В dev-режиме Vite проксирует /api → localhost:8000
// (настройка в vite.config.ts). В production читает VITE_API_URL.

import axios from "axios";
import type {
  Asset,
  AssetDetail,
  AssetType,
  Inspection,
  Repair,
  Failure,
  RiskScore,
  MaintenancePlan,
  AnalyticsSummary,
  TopRiskAsset,
  ModelMetrics,
} from "../types";

// Базовый URL: пустая строка = относительные пути (проксируются Vite в dev)
const baseURL = (import.meta as any).env?.VITE_API_URL || "";

export const http = axios.create({
  baseURL,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,   // 30 секунд — с запасом для переобучения модели
});


// ── Объекты электросети ───────────────────────────────────────────────────────

/** Список объектов с опциональной фильтрацией (используется в AssetsList) */
export const listAssets = (params?: {
  category?: string;
  region?: string;
  status?: string;
  skip?: number;
  limit?: number;
}) => http.get<Asset[]>("/api/assets", { params }).then((r) => r.data);

/** Справочник типов оборудования (для выпадающих списков) */
export const listAssetTypes = () =>
  http.get<{ id: number; name: string; category: string }[]>("/api/assets/types").then((r) => r.data);

/** Карточка объекта с агрегированными данными (используется в AssetDetail) */
export const getAsset = (id: number) =>
  http.get<AssetDetail>(`/api/assets/${id}`).then((r) => r.data);

/** Изменить статус объекта (active / maintenance / failed / decommissioned) */
export const updateAssetStatus = (id: number, status: string) =>
  http.put(`/api/assets/${id}/status`, null, { params: { status } }).then((r) => r.data);

/** Создать новый объект */
export const createAsset = (body: Partial<Asset>) =>
  http.post<Asset>("/api/assets", body).then((r) => r.data);

/** Полное редактирование объекта (PUT — обновляет только переданные поля) */
export const updateAsset = (id: number, body: Partial<Asset>) =>
  http.put<Asset>(`/api/assets/${id}`, body).then((r) => r.data);

/** Каскадное удаление объекта и всех связанных записей */
export const deleteAsset = (id: number) =>
  http.delete<void>(`/api/assets/${id}`).then((r) => r.data);


// ── Осмотры, ремонты, отказы ──────────────────────────────────────────────────

/** История осмотров конкретного объекта */
export const getAssetInspections = (id: number) =>
  http.get<Inspection[]>(`/api/inspections/asset/${id}`).then((r) => r.data);

/** Зафиксировать результат осмотра */
export const addInspection = (body: {
  asset_id: number;
  inspected_at: string;
  condition_score: number;
  defects_found?: string;
  notes?: string;
}) => http.post<Inspection>("/api/inspections", body).then((r) => r.data);

/** Редактировать запись об осмотре */
export const updateInspection = (id: number, body: Partial<Inspection>) =>
  http.put<Inspection>(`/api/inspections/${id}`, body).then((r) => r.data);

/** Удалить запись об осмотре */
export const deleteInspection = (id: number) =>
  http.delete<void>(`/api/inspections/${id}`).then((r) => r.data);

/** История ремонтов конкретного объекта */
export const getAssetRepairs = (id: number) =>
  http.get<Repair[]>(`/api/repairs/asset/${id}`).then((r) => r.data);

/** Зафиксировать ремонт */
export const addRepair = (body: any) =>
  http.post<Repair>("/api/repairs", body).then((r) => r.data);

/** Редактировать запись о ремонте */
export const updateRepair = (id: number, body: Partial<Repair>) =>
  http.put<Repair>(`/api/repairs/${id}`, body).then((r) => r.data);

/** Удалить запись о ремонте */
export const deleteRepair = (id: number) =>
  http.delete<void>(`/api/repairs/${id}`).then((r) => r.data);

/** Список всех отказов (последние 50) */
export const listFailures = () =>
  http.get<Failure[]>("/api/failures").then((r) => r.data);

/** История отказов конкретного объекта */
export const getAssetFailures = (id: number) =>
  http.get<Failure[]>(`/api/failures/asset/${id}`).then((r) => r.data);

/** Зарегистрировать факт отказа */
export const addFailure = (body: any) =>
  http.post<Failure>("/api/failures", body).then((r) => r.data);

/** Редактировать запись об отказе */
export const updateFailure = (id: number, body: Partial<Failure>) =>
  http.put<Failure>(`/api/failures/${id}`, body).then((r) => r.data);

/** Удалить запись об отказе */
export const deleteFailure = (id: number) =>
  http.delete<void>(`/api/failures/${id}`).then((r) => r.data);


// ── Риск и ML-модель ─────────────────────────────────────────────────────────

/** Рассчитать риск для одного объекта и сохранить в БД */
export const calculateRisk = (assetId: number) =>
  http.post<RiskScore>(`/api/risk/calculate/${assetId}`).then((r) => r.data);

/** Пакетный расчёт рисков для всех активных объектов */
export const calculateAllRisks = () =>
  http.post<{ calculated: number; results: any[] }>("/api/risk/calculate-all").then((r) => r.data);

/** Список последних риск-скоров (по одному на каждый объект) */
export const listRiskScores = () =>
  http.get<RiskScore[]>("/api/risk/scores").then((r) => r.data);

/** Переобучить ML-модель (занимает 1–3 минуты, GridSearchCV) */
export const retrainModel = () =>
  http.post<{ ok: boolean; metrics: ModelMetrics }>("/api/risk/retrain").then((r) => r.data);

/** Метрики текущей ML-модели (AUC, F1, признаки и т.д.) */
export const getModelMetrics = () =>
  http.get<ModelMetrics>("/api/risk/model-metrics").then((r) => r.data);


// ── Планирование ТОиР ─────────────────────────────────────────────────────────

/** Сгенерировать план ТОиР на horizon_days дней вперёд */
export const generateMaintenancePlan = (horizon_days = 180) =>
  http.post<{ generated: number; plan: any[] }>("/api/maintenance/generate", null, {
    params: { horizon_days },
  }).then((r) => r.data);

/** Список планов ТО с фильтрами */
export const listPlans = (params?: {
  status?: string;
  asset_id?: number;
  from_date?: string;
  to_date?: string;
}) => http.get<MaintenancePlan[]>("/api/maintenance/plans", { params }).then((r) => r.data);

/** Изменить статус записи плана (например, отметить как выполненную) */
export const updatePlanStatus = (id: number, status: string) =>
  http.put(`/api/maintenance/plans/${id}/status`, null, { params: { status } }).then((r) => r.data);


// ── Цифровая копия (Digital Twin) ─────────────────────────────────────────────

/** Перестроить граф digital twin из актуальных данных БД */
export const rebuildTwin = () =>
  http.post<{ ok: boolean; nodes: number; edges: number }>("/api/twin/rebuild").then((r) => r.data);

/** Полный граф сети: узлы + рёбра + критические цепочки */
export const getTwinGraph = () =>
  http.get<{
    nodes: any[];
    edges: any[];
    node_count: number;
    edge_count: number;
    critical_chains: any[];
  }>("/api/twin/graph").then((r) => r.data);

/** Состояние одного узла графа + downstream-зависимости */
export const getTwinNode = (id: number) =>
  http.get(`/api/twin/node/${id}`).then((r) => r.data);


// ── Аналитика ─────────────────────────────────────────────────────────────────

/** Сводные KPI для дашборда */
export const getAnalyticsSummary = () =>
  http.get<AnalyticsSummary>("/api/analytics/summary").then((r) => r.data);

/** Отказы по месяцам за последний год */
export const getFailuresByMonth = () =>
  http.get<{ month: string; count: number }[]>("/api/analytics/failures-by-month").then((r) => r.data);

/** Распределение объектов по уровням риска {low: N, medium: M, high: K} */
export const getRiskDistribution = () =>
  http.get<Record<string, number>>("/api/analytics/risk-distribution").then((r) => r.data);

/** Топ-N объектов с наибольшим риском (только high/medium, для дашборда) */
export const getTopRiskAssets = (limit = 10) =>
  http.get<TopRiskAsset[]>("/api/analytics/top-risk-assets", { params: { limit } }).then((r) => r.data);

/** Все объекты с последним риском (включая low и без риска, для страницы прогноза) */
export const getAllRiskAssets = () =>
  http.get<TopRiskAsset[]>("/api/analytics/all-risk-assets").then((r) => r.data);
