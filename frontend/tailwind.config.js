export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Archivo for everything, with a system stack behind it so the page is
        // readable before the webfont lands.
        sans: ['Archivo', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      colors: {
        // Interactive blue. Kept darker than the flag's light blue, which is
        // too pale to put text on.
        primary: {
          50: "#f0f9ff",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
        },
        // Chicago's flag: a white field, two light blue bars, four red stars.
        chicago: {
          blue: "#41B6E6",   // Pantone 298 - the bars
          red: "#C8102E",    // Pantone 186 - the stars
        },
      },
    },
  },
  plugins: [],
}
