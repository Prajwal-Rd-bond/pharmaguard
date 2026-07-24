/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#eefbf8",
          100: "#d4f4ec",
          200: "#aae8da",
          300: "#75d5c1",
          400: "#43bba5",
          500: "#279e8a",
          600: "#1c7f70",
          700: "#1a655a",
          800: "#19514a",
          900: "#18443f",
          950: "#082725",
        },
        ink: {
          50: "#f6f7f9",
          100: "#eceef2",
          200: "#d5dae2",
          300: "#b1bbc8",
          400: "#8695a9",
          500: "#66768d",
          600: "#525e74",
          700: "#434c5f",
          800: "#3a4150",
          900: "#333846",
          950: "#20232c",
        },
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 8px -2px rgb(20 40 60 / 0.08)",
        card: "0 2px 4px -1px rgb(20 40 60 / 0.06), 0 8px 24px -8px rgb(20 40 60 / 0.12)",
        glow: "0 0 0 1px rgb(39 158 138 / 0.15), 0 8px 30px -8px rgb(39 158 138 / 0.35)",
      },
      backgroundImage: {
        "grid-faint":
          "linear-gradient(to right, rgb(255 255 255 / 0.06) 1px, transparent 1px), linear-gradient(to bottom, rgb(255 255 255 / 0.06) 1px, transparent 1px)",
      },
      animation: {
        "fade-in": "fade-in 0.4s ease-out",
        "slide-up": "slide-up 0.4s ease-out",
      },
      keyframes: {
        "fade-in": { "0%": { opacity: 0 }, "100%": { opacity: 1 } },
        "slide-up": {
          "0%": { opacity: 0, transform: "translateY(8px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
