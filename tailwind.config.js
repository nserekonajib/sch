
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./templates/**/*.jinja",
    "./templates/**/*.jinja2",
    "./routes/**/*.py",
    "./static/**/*.js"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "sans-serif"]
      }
    }
  },
  plugins: [],
};
