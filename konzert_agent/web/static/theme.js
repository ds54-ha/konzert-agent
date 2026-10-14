// Hell/Dunkel und Akzentfarbe – pro Gerät im Browser gespeichert (auch für Gäste).
// Im <head> geladen, damit die Seite nicht erst hell aufblitzt.
const KA_THEME = (() => {
  const ACCENTS = [   // [Schlüssel, Name, hell, dunkel]
    ["orange", "Orange", "#e2471b", "#ff6a3d"],
    ["blau", "Blau", "#1d6fd8", "#5b9dff"],
    ["gruen", "Grün", "#2f7d32", "#7ccf6b"],
    ["violett", "Violett", "#6d3fd6", "#a88bff"],
    ["pink", "Pink", "#c2266e", "#ff6fae"],
    ["senf", "Senf", "#a86f00", "#f2b632"],
  ];
  const get = (k, d) => { try { const v = localStorage.getItem("ka:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
  const set = (k, v) => { try { localStorage.setItem("ka:" + k, JSON.stringify(v)); } catch {} };
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function apply() {
    const root = document.documentElement, theme = get("theme", "system");
    if (theme === "system") delete root.dataset.theme; else root.dataset.theme = theme;
    const dark = theme === "dark" || (theme === "system" && media.matches);
    const a = ACCENTS.find(x => x[0] === get("accent", "orange")) || ACCENTS[0];
    root.style.setProperty("--accent", dark ? a[3] : a[2]);
    root.style.setProperty("--accent-ink", dark ? "#130c08" : "#fff");
  }
  media.addEventListener("change", apply);
  apply();
  return {
    ACCENTS, apply,
    theme: () => get("theme", "system"), accent: () => get("accent", "orange"),
    setTheme(t) { set("theme", t); apply(); }, setAccent(a) { set("accent", a); apply(); },
  };
})();
