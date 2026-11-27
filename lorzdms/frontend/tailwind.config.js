/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: { sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
      colors: { brand: { 50: "#eef4ff", 100: "#dbe7ff", 200: "#bcd2ff", 500: "#2f6fed", 600: "#2259cc", 700: "#1c47a3" } },
    },
  },
  plugins: [],
};
