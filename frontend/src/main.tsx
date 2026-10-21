import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { applyTheme, getTheme } from "./lib/theme";
import "./index.css";

applyTheme(getTheme());

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root 요소를 찾을 수 없습니다.");

createRoot(rootEl).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
