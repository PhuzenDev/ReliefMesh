/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0C1013",
          900: "#10151A",
          800: "#171E24",
          700: "#1E2830",
          600: "#2A363F",
          500: "#3C4B56",
        },
        fog: {
          400: "#5E7180",
          300: "#8CA0AC",
          200: "#B7C6CD",
          100: "#E7EDF0",
        },
        triage: {
          immediate: "#D9463C",
          delayed: "#E8B23D",
          minor: "#4FA876",
          expectant: "#5E7180",
        },
        signal: {
          cyan: "#4FB4C7",
          amber: "#E8A33D",
        },
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["'IBM Plex Sans'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.25rem" }],
        sm: ["0.9375rem", { lineHeight: "1.4rem" }],
        base: ["1.0625rem", { lineHeight: "1.65rem" }],
        lg: ["1.1875rem", { lineHeight: "1.75rem" }],
        xl: ["1.3125rem", { lineHeight: "1.85rem" }],
        "2xl": ["1.625rem", { lineHeight: "2rem" }],
        "3xl": ["2rem", { lineHeight: "2.3rem" }],
      },
    },
  },
  plugins: [],
};
