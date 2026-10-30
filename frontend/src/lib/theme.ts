// Gestión del tema: claro / oscuro / sistema. La preferencia es de interfaz
// (no sensible), por lo que se guarda en localStorage según permite la
// especificación. "system" sigue el esquema del dispositivo en vivo.

export type ThemePreference = "light" | "dark" | "system";

const KEY = "theme";

function media(): MediaQueryList {
  return window.matchMedia("(prefers-color-scheme: dark)");
}

/** Preferencia guardada (default: "system"). */
export function getTheme(): ThemePreference {
  const stored = localStorage.getItem(KEY);
  return stored === "light" || stored === "dark" ? stored : "system";
}

/** ¿El tema efectivo ahora es oscuro? */
export function isDark(): boolean {
  const pref = getTheme();
  return pref === "system" ? media().matches : pref === "dark";
}

/** Guarda la preferencia y la aplica al documento. */
export function applyTheme(pref: ThemePreference): void {
  localStorage.setItem(KEY, pref);
  document.documentElement.classList.toggle("dark", isDark());
}

/** Aplica el tema antes del primer render (si cambia el SO, se re-aplica). */
export function initTheme(): void {
  applyTheme(getTheme());
  media().addEventListener("change", () => {
    if (getTheme() === "system") applyTheme("system");
  });
}
