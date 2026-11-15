// VI. The Ledger: redraws assets/ledger.svg from the public contribution calendar.
// Runs daily in .github/workflows/ledger.yml. No deps, no token (reads github.com like a visitor).
// usage: node scripts/ledger.mjs
import { readFileSync, writeFileSync } from "node:fs";

const USER = "Eurie92";
const INK = "#0b0a10", GILT = "#c9a46a", BONE = "#f1e4c6", UMBER = "#7a6443", MUTED = "#8b8597";
const fonts = JSON.parse(readFileSync(new URL("../assets/fonts.json", import.meta.url), "utf8"));

const now = new Date();
const iso = (d) => d.toISOString().slice(0, 10);
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

async function grab(from, to) {
  const r = await fetch(`https://github.com/users/${USER}/contributions?from=${from}&to=${to}`, {
    headers: { "user-agent": "profile-ledger" },
  });
  if (!r.ok) throw new Error(`github ${r.status}`);
  const html = await r.text();
  const cells = new Map();
  for (const m of html.matchAll(/<td[^>]*data-date="([\d-]+)"[^>]*id="([^"]+)"[^>]*data-level="(\d)"/g))
    cells.set(m[2], [m[1], Number(m[3])]);
  const days = [];
  for (const m of html.matchAll(/<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)/g)) {
    const c = cells.get(m[1]);
    if (!c) continue;
    const n = /^(\d+) contribution/.exec(m[2]);
    days.push({ date: c[0], count: n ? Number(n[1]) : 0, level: c[1] });
  }
  return days.filter((d) => d.date >= from && d.date <= to);
}

// github clamps a range to one calendar year, so stitch the last 12 months from two
const Y = now.getUTCFullYear();
const from = iso(new Date(Date.UTC(Y - 1, now.getUTCMonth(), now.getUTCDate() + 1)));
const to = iso(now);
const byDate = new Map();
for (const d of [...(await grab(`${Y - 1}-01-01`, `${Y - 1}-12-31`)), ...(await grab(`${Y}-01-01`, to))])
  if (d.date >= from && d.date <= to) byDate.set(d.date, d);
const days = [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
if (days.length < 300) throw new Error(`only ${days.length} days parsed, keeping the old ledger`);

const total = days.reduce((a, d) => a + d.count, 0);
let best = days[0], longest = 0, run = 0;
for (const d of days) {
  if (d.count > best.count) best = d;
  run = d.count ? run + 1 : 0;
  longest = Math.max(longest, run);
}
let current = 0;
for (let i = days.length - 1; i >= 0; i--) {
  if (days[i].count) current++;
  else if (i === days.length - 1) continue; // today can still be empty
  else break;
}
const active = days.filter((d) => d.count).length;

// grid: one column per week, Sunday on top, like github's own calendar
const W = 1200, H = 300, X0 = 92, Y0 = 70, CW = 19.6, CH = 19;
const GLYPH = ["·", ":", "+", "#", "@"];
const FILL = [UMBER, UMBER, GILT, GILT, BONE];
const OP = [0.35, 0.9, 0.75, 1, 1];
const start = new Date(days[0].date + "T00:00:00Z");
const offset = start.getUTCDay();
const layers = [[], [], [], [], []];
const months = [];
let lastMonth = -1;
days.forEach((d, i) => {
  const k = i + offset, col = Math.floor(k / 7), row = k % 7;
  const x = X0 + col * CW, y = Y0 + row * CH;
  layers[d.level].push(
    `<text x="${x.toFixed(1)}" y="${y}" style="animation-delay:${(col * 0.035).toFixed(2)}s"><title>${d.date}: ${d.count}</title>${GLYPH[d.level]}</text>`,
  );
  const m = new Date(d.date + "T00:00:00Z").getUTCMonth();
  if (m !== lastMonth && row === 0) {
    months.push(`<text x="${x.toFixed(1)}" y="${Y0 - 22}">${new Date(d.date).toLocaleString("en", { month: "short", timeZone: "UTC" }).toUpperCase()}</text>`);
    lastMonth = m;
  }
});
const grid = layers
  .map((l, lv) => `<g class="m c${lv}" font-size="15" fill="${FILL[lv]}" opacity="${OP[lv]}" text-anchor="middle">${l.join("")}</g>`)
  .join("");
const weekdays = ["", "MON", "", "WED", "", "FRI", ""]
  .map((t, r) => (t ? `<text x="${X0 - 26}" y="${Y0 + r * CH}" text-anchor="end">${t}</text>` : ""))
  .join("");

const stat = (x, value, label) =>
  `<text class="s" x="${x}" y="${H - 34}" font-size="40" fill="${BONE}">${esc(value)}</text>` +
  `<text class="m" x="${x}" y="${H - 14}" font-size="10" fill="${MUTED}" letter-spacing="2">${esc(label)}</text>`;
const bestDay = new Date(best.date + "T00:00:00Z").toLocaleString("en", { month: "short", day: "numeric", timeZone: "UTC" });

const css =
  `@font-face{font-family:S;src:url(data:font/woff2;base64,${fonts.serif}) format('woff2')}` +
  `@font-face{font-family:I;src:url(data:font/woff2;base64,${fonts["serif-i"]}) format('woff2')}` +
  `@font-face{font-family:M;src:url(data:font/woff2;base64,${fonts.mono}) format('woff2')}` +
  `.s{font-family:S,Georgia,serif}.i{font-family:I,Georgia,serif;font-style:italic}.m{font-family:M,ui-monospace,Consolas,monospace}` +
  `.m text{animation:in .6s ease-out both}@keyframes in{from{opacity:0}}` +
  `.c4 text{animation:in .6s ease-out both,pulse 3.2s ease-in-out 2s infinite}@keyframes pulse{50%{opacity:.55}}` +
  `@media (prefers-reduced-motion:reduce){*{animation:none!important}}`;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">
<title>${esc(`${total} contributions in the last year. Longest streak ${longest} days, current streak ${current} days.`)}</title>
<style>${css}</style><rect width="${W}" height="${H}" fill="${INK}"/>
<text class="m" x="40" y="26" font-size="10" fill="${UMBER}" letter-spacing="3">THE LEDGER · LAST 12 MONTHS · UPDATED ${to}</text>
<g class="m" font-size="10" fill="${MUTED}" letter-spacing="2">${months.join("")}${weekdays}</g>
${grid}
<line x1="40" x2="${W - 40}" y1="${H - 86}" y2="${H - 86}" stroke="${UMBER}" stroke-opacity=".5" stroke-dasharray="1 5"/>
${stat(40, total.toLocaleString("en"), "CONTRIBUTIONS")}${stat(300, `${active}`, "DAYS ON RECORD")}${stat(540, `${longest}d`, "LONGEST STREAK")}${stat(780, `${current}d`, "CURRENT STREAK")}${stat(1000, `${best.count}`, `BEST DAY · ${bestDay.toUpperCase()}`)}
</svg>`;

writeFileSync(new URL("../assets/ledger.svg", import.meta.url), svg);
console.log(`ledger: ${total} contributions, longest ${longest}d, current ${current}d`);
