import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import ForgotCheckoutSheet from "./components/ForgotCheckoutSheet";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import DashboardPage from "./pages/DashboardPage";
import TransportPage from "./pages/TransportPage";
import HoursPage from "./pages/HoursPage";
import PlannerPage from "./pages/PlannerPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            {/* Sin autenticación: la raíz abre directo el Dashboard. */}
            <Route path="/" element={<DashboardPage />} />
            <Route path="/transporte" element={<TransportPage />} />
            <Route path="/horas" element={<HoursPage />} />
            <Route path="/planificador" element={<PlannerPage />} />
            <Route path="/ajustes" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      {/* Prompt global: visible desde cualquier pantalla. */}
      <ForgotCheckoutSheet />
    </ToastProvider>
  );
}
