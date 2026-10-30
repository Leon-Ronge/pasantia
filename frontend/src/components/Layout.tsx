import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { applyTheme, getTheme, type ThemePreference } from "../lib/theme";
import { fmtDateShort, longDate, todayISO } from "../lib/format";
import SegmentedControl from "./SegmentedControl";
import {
  IconBus,
  IconCalendar,
  IconClock,
  IconDashboard,
  IconMonitor,
  IconMoon,
  IconSliders,
  IconSun,
} from "./icons";

/** Secciones principales: Inicio, Horas, Viajes, Ajustes. */
const NAV = [
  { to: "/", label: "Inicio", Icon: IconDashboard, end: true },
  { to: "/horas", label: "Horas", Icon: IconClock },
  { to: "/transporte", label: "Viajes", Icon: IconBus },
  { to: "/ajustes", label: "Ajustes", Icon: IconSliders },
];

/** Secundaria del grupo Horas (misma sección, entrada dedicada). */
const NAV_SUB = [
  { to: "/planificador", label: "Planificador", Icon: IconCalendar },
];

const THEME_OPTIONS: {
  value: ThemePreference;
  label: string;
  icon: JSX.Element;
}[] = [
  { value: "light", label: "Claro", icon: <IconSun className="h-4 w-4" /> },
  { value: "dark", label: "Oscuro", icon: <IconMoon className="h-4 w-4" /> },
  { value: "system", label: "Sistema", icon: <IconMonitor className="h-4 w-4" /> },
];

export default function Layout() {
  const [theme, setTheme] = useState<ThemePreference>(() => getTheme());
  const today = todayISO();

  const changeTheme = (pref: ThemePreference) => {
    setTheme(pref);
    applyTheme(pref);
  };

  return (
    <div className="min-h-screen">
      {/* ------------------------------------------- Navegación lateral (escritorio) */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-surface lg:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-on-accent">
            <IconClock className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold">Pasantía</p>
            <p className="text-xs text-muted">horas y viajes</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-medium transition ${
                  isActive
                    ? "bg-accent-soft text-accent-strong"
                    : "text-muted hover:bg-surface-2 hover:text-fg"
                }`
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
          <div className="pt-2">
            <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted">
              Horas
            </p>
            {NAV_SUB.map(({ to, label, Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex min-h-[44px] items-center gap-3 rounded-xl px-3 pl-9 text-sm font-medium transition ${
                    isActive
                      ? "bg-accent-soft text-accent-strong"
                      : "text-muted hover:bg-surface-2 hover:text-fg"
                  }`
                }
              >
                <Icon className="h-5 w-5" />
                {label}
              </NavLink>
            ))}
          </div>
        </nav>
        <div className="border-t border-line p-3">
          <SegmentedControl
            value={theme}
            options={THEME_OPTIONS}
            onChange={changeTheme}
            ariaLabel="Tema de la interfaz"
            className="w-full"
          />
        </div>
      </aside>

      {/* --------------------------------------------------------- Contenido */}
      <div className="lg:pl-60">
        {/* Cabecera compartida: fecha de hoy + tema (móvil y tablet). */}
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-line bg-surface/90 px-4 py-2.5 backdrop-blur lg:justify-end">
          <div className="lg:hidden">
            <p className="text-sm font-semibold leading-tight">Pasantía</p>
            <p className="text-xs text-muted" title={longDate(today)}>
              {longDate(today)}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-muted lg:inline">
              {fmtDateShort(today)}
            </span>
            <SegmentedControl
              value={theme}
              options={THEME_OPTIONS.map((o) => ({
                value: o.value,
                icon: o.icon,
              }))}
              onChange={changeTheme}
              ariaLabel="Tema de la interfaz"
            />
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-5 lg:pb-10">
          <Outlet />
        </main>
      </div>

      {/* ------------------------------------- Navegación inferior (móvil) */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
        aria-label="Secciones"
      >
        <div className="grid grid-cols-4">
          {NAV.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `relative flex min-h-[56px] flex-col items-center justify-center gap-0.5 pt-1 text-xs font-medium transition ${
                  isActive ? "text-accent-strong" : "text-muted"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    <span
                      aria-hidden
                      className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-accent"
                    />
                  ) : null}
                  <Icon className="h-5 w-5" />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
