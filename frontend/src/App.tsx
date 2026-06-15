// App.tsx — корневой компонент маршрутизации.
// Все страницы оборачиваются в Layout (боковая панель + основной контент).
// Неизвестные пути перенаправляются на главную страницу (Navigate to="/").

import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";           // / — дашборд с KPI
import AssetsList from "./pages/AssetsList";          // /assets — реестр объектов
import AssetDetail from "./pages/AssetDetail";        // /assets/:id — карточка объекта
import RepairsList from "./pages/RepairsList";        // /repairs — все ремонты
import FailuresList from "./pages/FailuresList";      // /failures — все отказы
import RiskAnalytics from "./pages/RiskAnalytics";   // /risk — прогноз отказов
import MaintenancePlanPage from "./pages/MaintenancePlan"; // /maintenance — план ТОиР
import AnalyticsPage from "./pages/Analytics";        // /analytics — детальная аналитика

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/"            element={<Dashboard />} />
        <Route path="/assets"      element={<AssetsList />} />
        <Route path="/assets/:id"  element={<AssetDetail />} />
        <Route path="/repairs"     element={<RepairsList />} />
        <Route path="/failures"    element={<FailuresList />} />
        <Route path="/risk"        element={<RiskAnalytics />} />
        <Route path="/maintenance" element={<MaintenancePlanPage />} />
        <Route path="/analytics"   element={<AnalyticsPage />} />
        {/* Любой неизвестный маршрут → главная */}
        <Route path="*"            element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
