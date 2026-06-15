// Layout.tsx — общая оболочка всех страниц: боковая панель + основная область.
// Рендерится один раз и остаётся mounted при переходах между страницами.
// NavLink автоматически добавляет класс sidebar__link--active для активного пункта.

import { ReactNode } from "react";
import { NavLink } from "react-router-dom";

// Пункты навигационного меню
const NAV = [
  { to: "/",            label: "Дашборд",         icon: "📊" },
  { to: "/assets",      label: "Реестр объектов", icon: "🔌" },
  { to: "/repairs",     label: "Ремонты",         icon: "🔧" },
  { to: "/failures",    label: "Отказы",          icon: "💥" },
  { to: "/risk",        label: "Прогноз отказов", icon: "⚠️" },
  { to: "/maintenance", label: "План ТОиР",       icon: "🛠️" },
  { to: "/analytics",   label: "Аналитика",       icon: "📈" },
];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      {/* Боковая панель с брендингом и навигацией */}
      <aside className="sidebar">
        <div className="sidebar__brand">
          <div>
            <strong>PowerGrid</strong>
            <span>PowerGrid System</span>
          </div>
        </div>
        <nav className="sidebar__nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}   // end=true: активен только при точном совпадении "/"
              className={({ isActive }) =>
                "sidebar__link" + (isActive ? " sidebar__link--active" : "")
              }
            >
              <span style={{ marginRight: 8 }}>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Основная область контента — сюда рендерится текущая страница */}
      <main className="main">{children}</main>
    </div>
  );
}
