// main.tsx — точка входа React-приложения.
// Монтирует компонент App в div#root (см. index.html).
// BrowserRouter включает HTML5 History API (навигация без перезагрузки страницы).
// React.StrictMode в dev-режиме делает двойной рендер для выявления побочных эффектов.

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";   // глобальные стили (CSS-переменные, сетка, компоненты)

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
