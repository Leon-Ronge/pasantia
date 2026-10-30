/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Tokens semánticos: mapean a variables CSS (:root claro / .dark).
      // Un solo acento (ámbar); success/warning/error solo para estados.
      colors: {
        bg: "var(--bg)",
        surface: { DEFAULT: "var(--surface)", 2: "var(--surface-2)" },
        fg: "var(--fg)",
        muted: "var(--muted)",
        line: "var(--line)",
        accent: {
          DEFAULT: "var(--accent)",
          strong: "var(--accent-strong)",
          soft: "var(--accent-soft)",
        },
        "on-accent": "var(--on-accent)",
        success: {
          DEFAULT: "var(--success)",
          strong: "var(--success-strong)",
          soft: "var(--success-soft)",
        },
        "on-success": "var(--on-success)",
        warning: {
          DEFAULT: "var(--warning)",
          strong: "var(--warning-strong)",
          soft: "var(--warning-soft)",
        },
        error: {
          DEFAULT: "var(--error)",
          strong: "var(--error-strong)",
          soft: "var(--error-soft)",
        },
        "on-error": "var(--on-error)",
        // Compatibilidad con las páginas existentes: el acento viejo (azul)
        // se reemplaza por el ámbar del sistema de diseño.
        brand: {
          50: "#fffbeb",
          100: "#fef3c7",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      // Mínimo del sistema: 13 px (xs); 14 px en tablas (sm).
      fontSize: {
        xs: ["13px", { lineHeight: "18px" }],
        sm: ["14px", { lineHeight: "20px" }],
        base: ["15px", { lineHeight: "22px" }],
        lg: ["17px", { lineHeight: "24px" }],
        xl: ["20px", { lineHeight: "28px" }],
        "2xl": ["24px", { lineHeight: "30px" }],
        "3xl": ["30px", { lineHeight: "36px" }],
      },
      boxShadow: { soft: "var(--shadow)" },
    },
  },
  plugins: [],
};
