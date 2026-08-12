/* ---------------------------------------------------------------------------
   Merchant Sales & Voucher Intelligence - offline report
   ---------------------------------------------------------------------------
   Every visual is computed in the browser from the embedded columnar arrays,
   so the slicers cross-filter for real rather than switching between
   pre-rendered images. Chart specs follow the dataviz method: thin marks,
   4px rounded data-ends on the value end only, 2px surface gaps between
   stacked segments, direct value labels (mandatory here - three light-mode
   series colours sit below 3:1 on the light surface), one y-scale per chart,
   and a legend whenever two or more series share a plot.
--------------------------------------------------------------------------- */
"use strict";

const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5"];
const cssv = (name) => getComputedStyle(document.documentElement)
  .getPropertyValue(name).trim();
const seriesColor = (i) => cssv(SERIES[i % SERIES.length]);
const STATUS = { good: "--good", warning: "--warning", serious: "--serious", critical: "--critical" };

/* ------------------------------------------------------------- formatting */
const zar = (n, dp = 0) => "R" + Number(n).toLocaleString("en-ZA",
  { minimumFractionDigits: dp, maximumFractionDigits: dp });
const compact = (n) => {
  const a = Math.abs(n);
  if (a >= 1e9) return "R" + (n / 1e9).toFixed(1) + "bn";
  if (a >= 1e6) return "R" + (n / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "m";
  if (a >= 1e3) return "R" + (n / 1e3).toFixed(0) + "k";
  return "R" + n.toFixed(0);
};
const num = (n, dp = 0) => Number(n).toLocaleString("en-ZA",
  { minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = (n, dp = 1) => Number(n).toFixed(dp) + "%";
const signed = (n, dp = 1) => (n >= 0 ? "+" : "") + Number(n).toFixed(dp) + "%";

/* ------------------------------------------------------------ derived maps */
const M = DATA.merch;
const REGIONS = [...new Set(M.map((m) => m.r))].sort();
const CHANNELS = [...new Set(M.map((m) => m.c))].sort();
const MONTHS = DATA.meta.months;
const NMONTH = MONTHS.length;
const segNames = DATA.ml.segments.map((s) => s.Segment);
const segColor = (name) => seriesColor(segNames.indexOf(name));

const state = {
  regions: new Set(REGIONS),
  vtypes: new Set(DATA.vt),
  channels: new Set(CHANNELS),
  from: 0,
  to: NMONTH - 1,
  page: "exec",
  sortMerch: { key: "sales", dir: -1 },
  sortOps: { key: "per1k", dir: -1 },
};

/* --------------------------------------------------------------- filtering */
function masks() {
  const merchOK = M.map((m) => state.regions.has(m.r) && state.channels.has(m.c));
  const vtOK = DATA.vt.map((v) => state.vtypes.has(v));
  const dateOK = DATA.dateMonth.map((mo) => mo >= state.from && mo <= state.to);
  return { merchOK, vtOK, dateOK };
}

/* Aggregates recomputed on every filter change. Kept in one place so a visual
   can never quietly disagree with the tile above it. */
function aggregate() {
  const { merchOK, vtOK, dateOK } = masks();
  const S = DATA.sales, T = DATA.tick, R = DATA.red;

  const byDate = new Float64Array(DATA.dates.length);
  const txByDate = new Float64Array(DATA.dates.length);
  const byMonth = new Float64Array(NMONTH);
  const txByMonth = new Float64Array(NMONTH);
  const byMerch = new Float64Array(M.length);
  const txByMerch = new Float64Array(M.length);
  const byRegion = {}; REGIONS.forEach((r) => (byRegion[r] = 0));
  const regionMonth = {}; REGIONS.forEach((r) => (regionMonth[r] = new Float64Array(NMONTH)));
  const byVt = new Float64Array(DATA.vt.length);
  const vtMonth = DATA.vt.map(() => new Float64Array(NMONTH));
  const merchMonth = M.map(() => new Float64Array(NMONTH));
  let totalSales = 0, totalTx = 0;

  for (let i = 0; i < S.d.length; i++) {
    const d = S.d[i], m = S.m[i], v = S.v[i];
    if (!dateOK[d] || !merchOK[m] || !vtOK[v]) continue;
    const val = S.s[i], tx = S.t[i], mo = DATA.dateMonth[d];
    byDate[d] += val; txByDate[d] += tx;
    byMonth[mo] += val; txByMonth[mo] += tx;
    byMerch[m] += val; txByMerch[m] += tx;
    byRegion[M[m].r] += val; regionMonth[M[m].r][mo] += val;
    byVt[v] += val; vtMonth[v][mo] += val;
    merchMonth[m][mo] += val;
    totalSales += val; totalTx += tx;
  }

  // Tickets carry no voucher type, so the voucher slicer cannot filter them.
  // Applying it anyway would silently drop tickets and understate the
  // operational picture; the filter bar says so.
  let tickets = 0, resSum = 0, breaches = 0, open = 0;
  const tkByMonth = new Float64Array(NMONTH);
  const brByMonth = new Float64Array(NMONTH);
  const tkByMerch = new Float64Array(M.length);
  const brByMerch = new Float64Array(M.length);
  const resByMerch = new Float64Array(M.length);
  const tkByPrio = DATA.prio.map(() => ({ n: 0, res: 0, br: 0 }));
  const tkByType = DATA.tt.map(() => ({ n: 0, res: 0, br: 0 }));
  const status = { Closed: 0, Open: 0, Escalated: 0, "Pending Merchant": 0 };
  for (let i = 0; i < T.d.length; i++) {
    const d = T.d[i], m = T.m[i];
    if (!dateOK[d] || !merchOK[m]) continue;
    const mo = DATA.dateMonth[d];
    tickets++; resSum += T.res[i]; breaches += T.br[i]; open += T.op[i];
    tkByMonth[mo]++; brByMonth[mo] += T.br[i];
    tkByMerch[m]++; brByMerch[m] += T.br[i]; resByMerch[m] += T.res[i];
    const p = tkByPrio[T.p[i]]; p.n++; p.res += T.res[i]; p.br += T.br[i];
    const ty = tkByType[T.tt[i]]; ty.n++; ty.res += T.res[i]; ty.br += T.br[i];
  }

  let vouchers = 0, redeemed = 0, daysSum = 0, delayed = 0, voucherVal = 0;
  const redMonth = new Float64Array(NMONTH), soldMonth = new Float64Array(NMONTH);
  const vtRed = DATA.vt.map(() => ({ n: 0, rd: 0, sd: 0, dl: 0, val: 0 }));
  const merchRed = M.map(() => ({ n: 0, rd: 0, sd: 0, dl: 0 }));
  for (let i = 0; i < R.m.length; i++) {
    const m = R.m[i], v = R.v[i], mo = R.mo[i];
    if (!merchOK[m] || !vtOK[v] || mo < state.from || mo > state.to) continue;
    vouchers += R.n[i]; redeemed += R.rd[i]; daysSum += R.sd[i];
    delayed += R.dl[i]; voucherVal += R.val[i];
    soldMonth[mo] += R.n[i]; redMonth[mo] += R.rd[i];
    const a = vtRed[v]; a.n += R.n[i]; a.rd += R.rd[i]; a.sd += R.sd[i];
    a.dl += R.dl[i]; a.val += R.val[i];
    const b = merchRed[m]; b.n += R.n[i]; b.rd += R.rd[i]; b.sd += R.sd[i]; b.dl += R.dl[i];
  }

  const activeMonths = [];
  for (let i = state.from; i <= state.to; i++) activeMonths.push(i);

  return {
    merchOK, vtOK, dateOK, activeMonths,
    totalSales, totalTx, byDate, txByDate, byMonth, txByMonth, byMerch,
    txByMerch, byRegion, regionMonth, byVt, vtMonth, merchMonth,
    tickets, resSum, breaches, open, tkByMonth, brByMonth, tkByMerch,
    brByMerch, resByMerch, tkByPrio, tkByType, status,
    vouchers, redeemed, daysSum, delayed, voucherVal, redMonth, soldMonth,
    vtRed, merchRed,
  };
}

/* ============================================================ chart toolkit */
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, text) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null)
    n.setAttribute(k, attrs[k]);
  if (text !== undefined) n.textContent = text;
  return n;
};

const tip = document.getElementById("tooltip");
function showTip(evt, title, rows) {
  tip.innerHTML = `<div class="tt-title">${title}</div>` + rows
    .map((r) => `<div class="tt-row"><span>${r[0]}</span><b>${r[1]}</b></div>`).join("");
  tip.style.opacity = "1";
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
const hideTip = () => { tip.style.opacity = "0"; };

/* Hover is the default layer on every mark, per the interaction spec. */
function hoverable(node, title, rows, onClick) {
  node.addEventListener("mousemove", (e) => showTip(e, title, rows));
  node.addEventListener("mouseleave", hideTip);
  if (onClick) {
    node.style.cursor = "pointer";
    node.addEventListener("click", () => { hideTip(); onClick(); });
  }
}

function frame(svg, height) {
  svg.innerHTML = "";
  const w = Math.max(260, svg.parentElement.clientWidth || 520);
  svg.setAttribute("viewBox", `0 0 ${w} ${height}`);
  svg.setAttribute("width", w);
  svg.setAttribute("height", height);
  return w;
}

function niceMax(v) {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const s = v / mag;
  return (s <= 1 ? 1 : s <= 2 ? 2 : s <= 2.5 ? 2.5 : s <= 5 ? 5 : 10) * mag;
}

/* Horizontal bars: the form for ranking by magnitude with readable labels. */
function barsH(svg, rows, opts = {}) {
  const { fmt = compact, color = seriesColor(0), onClick, height } = opts;
  const rowH = 26, padT = 6, padB = 8;
  const h = height || rows.length * rowH + padT + padB;
  const w = frame(svg, h);
  const labelW = Math.min(190, Math.max(...rows.map((r) => r.label.length)) * 6.6 + 10);
  const valW = 62;
  const plotW = Math.max(30, w - labelW - valW - 8);
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1);

  rows.forEach((r, i) => {
    const y = padT + i * rowH;
    const bw = Math.max(2, (Math.abs(r.value) / max) * plotW);
    const g = el("g");
    g.appendChild(el("rect", {
      x: 0, y, width: w, height: rowH - 4, fill: "transparent",
    }));
    g.appendChild(el("text", {
      x: 0, y: y + rowH / 2 + 1, "dominant-baseline": "middle", class: "axislabel",
      fill: cssv("--text-secondary"),
    }, r.label));
    // 4px rounded end on the value end only; the baseline end stays square.
    g.appendChild(el("rect", {
      x: labelW, y: y + 4, width: bw, height: rowH - 14, rx: 4,
      fill: r.color || color,
    }));
    g.appendChild(el("rect", {
      x: labelW, y: y + 4, width: Math.min(4, bw), height: rowH - 14,
      fill: r.color || color,
    }));
    g.appendChild(el("text", {
      x: labelW + bw + 7, y: y + rowH / 2 + 1, "dominant-baseline": "middle",
      class: "vallabel",
    }, fmt(r.value)));
    hoverable(g, r.label, r.tip || [["Value", fmt(r.value)]],
      onClick ? () => onClick(r) : null);
    svg.appendChild(g);
  });
}

/* Line chart with a crosshair; used for anything over time. */
function lineChart(svg, series, xLabels, opts = {}) {
  const { fmt = compact, height = 230, yZero = true, area = false,
    bands = null, xTickEvery } = opts;
  const w = frame(svg, height);
  const padL = 54, padR = 12, padT = 10, padB = 26;
  const plotW = w - padL - padR, plotH = height - padT - padB;
  const all = series.flatMap((s) => s.points).filter((v) => v !== null && !isNaN(v));
  const bandVals = bands ? bands.flatMap((b) => [b.lo, b.hi]) : [];
  let max = niceMax(Math.max(...all, ...bandVals));
  let min = yZero ? 0 : Math.min(...all, ...bandVals) * 0.98;
  const n = xLabels.length;
  const X = (i) => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const Y = (v) => padT + plotH - ((v - min) / (max - min || 1)) * plotH;

  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4, y = Y(v);
    svg.appendChild(el("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "gridline" }));
    svg.appendChild(el("text", { x: padL - 8, y: y + 3.5, "text-anchor": "end", class: "axislabel" }, fmt(v)));
  }
  const every = xTickEvery || Math.ceil(n / 8);
  xLabels.forEach((lab, i) => {
    if (i % every && i !== n - 1) return;
    svg.appendChild(el("text", {
      x: X(i), y: height - 8, "text-anchor": "middle", class: "axislabel",
    }, lab));
  });
  svg.appendChild(el("line", {
    x1: padL, x2: w - padR, y1: padT + plotH, y2: padT + plotH, class: "baseline",
  }));

  if (bands) {
    const up = bands.map((b, i) => `${X(b.i)},${Y(b.hi)}`).join(" ");
    const dn = bands.map((b, i) => `${X(b.i)},${Y(b.lo)}`).reverse().join(" ");
    svg.appendChild(el("polygon", {
      points: up + " " + dn, fill: seriesColor(1), opacity: 0.14,
    }));
  }

  series.forEach((s) => {
    const pts = s.points.map((v, i) => (v === null ? null : [X(i), Y(v)]))
      .filter(Boolean);
    if (!pts.length) return;
    if (area) {
      svg.appendChild(el("polygon", {
        points: `${pts[0][0]},${padT + plotH} ` + pts.map((p) => p.join(",")).join(" ")
          + ` ${pts[pts.length - 1][0]},${padT + plotH}`,
        fill: s.color, opacity: 0.12,
      }));
    }
    svg.appendChild(el("polyline", {
      points: pts.map((p) => p.join(",")).join(" "), fill: "none",
      stroke: s.color, "stroke-width": s.width || 2,
      "stroke-dasharray": s.dash || null,
      "stroke-linejoin": "round", "stroke-linecap": "round",
    }));
  });

  // Crosshair over the whole plot: one hit target per x position, larger than
  // the marks themselves.
  const cross = el("line", {
    x1: 0, x2: 0, y1: padT, y2: padT + plotH, stroke: cssv("--axis"),
    "stroke-width": 1, opacity: 0,
  });
  svg.appendChild(cross);
  const dots = series.map((s) => {
    const c = el("circle", { r: 4.5, fill: s.color, stroke: cssv("--surface-1"), "stroke-width": 2, opacity: 0 });
    svg.appendChild(c); return c;
  });
  const hit = el("rect", { x: padL, y: padT, width: plotW, height: plotH, fill: "transparent" });
  hit.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * w;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - padL) / plotW) * (n - 1))));
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i));
    cross.setAttribute("opacity", 1);
    series.forEach((s, k) => {
      const v = s.points[i];
      if (v === null || v === undefined || isNaN(v)) { dots[k].setAttribute("opacity", 0); return; }
      dots[k].setAttribute("cx", X(i)); dots[k].setAttribute("cy", Y(v));
      dots[k].setAttribute("opacity", 1);
    });
    showTip(e, xLabels[i], series.filter((s) => s.points[i] !== null && !isNaN(s.points[i]))
      .map((s) => [s.name, fmt(s.points[i])]));
  });
  hit.addEventListener("mouseleave", () => {
    cross.setAttribute("opacity", 0);
    dots.forEach((d) => d.setAttribute("opacity", 0));
    hideTip();
  });
  svg.appendChild(hit);
}

/* Vertical bars, optionally stacked. 2px surface gap between segments. */
function barsV(svg, groups, seriesDefs, opts = {}) {
  const { fmt = compact, height = 250, stacked = true, labelTop = true, onClick } = opts;
  const w = frame(svg, height);
  const padL = 54, padR = 10, padT = 14, padB = 28;
  const plotW = w - padL - padR, plotH = height - padT - padB;
  const totals = groups.map((g) => stacked
    ? g.values.reduce((a, b) => a + b, 0) : Math.max(...g.values));
  const max = niceMax(Math.max(...totals, 1));
  const Y = (v) => padT + plotH - (v / max) * plotH;
  const bw = Math.min(58, (plotW / groups.length) * (stacked ? 0.62 : 0.78));

  for (let i = 0; i <= 4; i++) {
    const v = (max * i) / 4, y = Y(v);
    svg.appendChild(el("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "gridline" }));
    svg.appendChild(el("text", { x: padL - 8, y: y + 3.5, "text-anchor": "end", class: "axislabel" }, fmt(v)));
  }
  svg.appendChild(el("line", { x1: padL, x2: w - padR, y1: Y(0), y2: Y(0), class: "baseline" }));

  groups.forEach((g, gi) => {
    const cx = padL + (plotW / groups.length) * (gi + 0.5);
    svg.appendChild(el("text", {
      x: cx, y: height - 9, "text-anchor": "middle", class: "axislabel",
    }, g.label));

    if (stacked) {
      let acc = 0;
      g.values.forEach((v, si) => {
        if (v <= 0) return;
        const y0 = Y(acc + v), y1 = Y(acc);
        const hgt = Math.max(1, y1 - y0 - 2); // 2px surface gap between segments
        const seg = el("rect", {
          x: cx - bw / 2, y: y0, width: bw, height: hgt,
          rx: si === g.values.length - 1 ? 4 : 0, fill: seriesDefs[si].color,
        });
        hoverable(seg, `${g.label} - ${seriesDefs[si].name}`,
          [["Value", fmt(v)], ["Share of month", pct((v / (acc + v || 1)) * 0 + (v / totals[gi]) * 100)]]);
        svg.appendChild(seg);
        acc += v;
      });
      if (labelTop) svg.appendChild(el("text", {
        x: cx, y: Y(totals[gi]) - 6, "text-anchor": "middle", class: "vallabel",
      }, fmt(totals[gi])));
    } else {
      const inner = bw / g.values.length;
      g.values.forEach((v, si) => {
        const x = cx - bw / 2 + si * inner;
        const bar = el("rect", {
          x: x + 1, y: Y(v), width: Math.max(2, inner - 2),
          height: Math.max(1, Y(0) - Y(v)), rx: 4, fill: seriesDefs[si].color,
        });
        hoverable(bar, g.label, [[seriesDefs[si].name, fmt(v)]],
          onClick ? () => onClick(g, si) : null);
        svg.appendChild(bar);
        if (labelTop) svg.appendChild(el("text", {
          x: x + inner / 2, y: Y(v) - 5, "text-anchor": "middle", class: "vallabel",
        }, fmt(v)));
      });
    }
  });
}

/* Scatter / bubble. Colour is identity, so at most three categorical slots -
   the all-pairs cap from the palette validation. */
function scatter(svg, points, opts = {}) {
  const { height = 300, xLabel = "", yLabel = "", fmtX = compact,
    fmtY = (v) => v.toFixed(1), onClick } = opts;
  const w = frame(svg, height);
  const padL = 56, padR = 16, padT = 14, padB = 40;
  const plotW = w - padL - padR, plotH = height - padT - padB;
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const xMin = Math.min(...xs, 0), xMax = niceMax(Math.max(...xs));
  const yMin = Math.min(...ys) * 1.15, yMax = Math.max(...ys) * 1.15;
  const X = (v) => padL + ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const Y = (v) => padT + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const rMax = Math.max(...points.map((p) => p.r || 1), 1);

  for (let i = 0; i <= 4; i++) {
    const v = yMin + ((yMax - yMin) * i) / 4, y = Y(v);
    svg.appendChild(el("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "gridline" }));
    svg.appendChild(el("text", { x: padL - 8, y: y + 3.5, "text-anchor": "end", class: "axislabel" }, fmtY(v)));
  }
  for (let i = 0; i <= 4; i++) {
    const v = xMin + ((xMax - xMin) * i) / 4;
    svg.appendChild(el("text", { x: X(v), y: height - 20, "text-anchor": "middle", class: "axislabel" }, fmtX(v)));
  }
  if (yMin < 0 && yMax > 0) svg.appendChild(el("line", {
    x1: padL, x2: w - padR, y1: Y(0), y2: Y(0), class: "baseline",
  }));
  svg.appendChild(el("text", {
    x: padL + plotW / 2, y: height - 4, "text-anchor": "middle", class: "axislabel",
  }, xLabel));
  svg.appendChild(el("text", {
    x: 12, y: padT + plotH / 2, "text-anchor": "middle", class: "axislabel",
    transform: `rotate(-90 12 ${padT + plotH / 2})`,
  }, yLabel));

  points.forEach((p) => {
    const r = 5 + Math.sqrt((p.r || 0) / rMax) * 12;
    // 2px surface ring so overlapping bubbles stay separable.
    const c = el("circle", {
      cx: X(p.x), cy: Y(p.y), r, fill: p.color, "fill-opacity": 0.68,
      stroke: cssv("--surface-1"), "stroke-width": 2,
    });
    hoverable(c, p.label, p.tip, onClick ? () => onClick(p) : null);
    svg.appendChild(c);
  });
  // Direct-label the extremes only - never a label on every point.
  const extremes = [...points].sort((a, b) => b.y - a.y).slice(0, 2)
    .concat([...points].sort((a, b) => a.y - b.y).slice(0, 2));
  extremes.forEach((p) => {
    const r = 5 + Math.sqrt((p.r || 0) / rMax) * 12;
    svg.appendChild(el("text", {
      x: X(p.x), y: Y(p.y) - r - 5, "text-anchor": "middle", class: "vallabel",
    }, p.label));
  });
}

/* Sequential heat grid - one hue, light to dark, for continuous magnitude. */
function heatgrid(svg, rows, cols, values, opts = {}) {
  const { height, fmt = (v) => v.toFixed(1), onHover } = opts;
  const cellH = 26, padT = 22;
  const labelW = Math.min(120, Math.max(...rows.map((r) => r.length)) * 6.4 + 8);
  const h = height || rows.length * cellH + padT + 8;
  const w = frame(svg, h);
  const cellW = (w - labelW - 4) / cols.length;
  const flat = values.flat().filter((v) => v !== null && !isNaN(v));
  const lo = Math.min(...flat), hi = Math.max(...flat);
  const ramp = ["--seq-100", "--seq-250", "--seq-400", "--seq-550", "--seq-700"].map(cssv);
  const colorFor = (v) => {
    const t = (v - lo) / (hi - lo || 1);
    return ramp[Math.min(ramp.length - 1, Math.floor(t * ramp.length))];
  };

  cols.forEach((c, j) => svg.appendChild(el("text", {
    x: labelW + cellW * (j + 0.5), y: 13, "text-anchor": "middle", class: "axislabel",
  }, c)));
  rows.forEach((r, i) => {
    svg.appendChild(el("text", {
      x: 0, y: padT + i * cellH + cellH / 2, "dominant-baseline": "middle",
      class: "axislabel", fill: cssv("--text-secondary"),
    }, r));
    cols.forEach((c, j) => {
      const v = values[i][j];
      if (v === null || isNaN(v)) return;
      const cell = el("rect", {
        x: labelW + cellW * j + 1, y: padT + i * cellH + 1,
        width: cellW - 2, height: cellH - 2, rx: 3, fill: colorFor(v),
      });
      hoverable(cell, `${r} - ${c}`, onHover ? onHover(i, j, v) : [["Value", fmt(v)]]);
      svg.appendChild(cell);
      // Value printed in every cell: the relief rule, and a heat map without
      // numbers is unreadable at these dimensions anyway.
      const t = (v - lo) / (hi - lo || 1);
      svg.appendChild(el("text", {
        x: labelW + cellW * (j + 0.5), y: padT + i * cellH + cellH / 2 + 1,
        "text-anchor": "middle", "dominant-baseline": "middle",
        fill: t > 0.55 ? "#fff" : cssv("--text-primary"),
        "font-size": 10.5,
      }, fmt(v)));
    });
  });
}

/* --------------------------------------------------------------- the map --
   Equirectangular projection with the x axis scaled by cos(mean latitude).
   At South Africa's extent that is accurate to well under a pixel and needs no
   projection library; an unscaled lon/lat plot would stretch the country about
   14% too wide, which is visible and wrong.

   Sequential metrics use the one-hue blue ramp. Momentum uses the diverging
   blue-to-red pair with a neutral gray midpoint, because it has a meaningful
   zero. Provinces with no merchants are hatched, never shaded: colouring them
   as zero would claim they underperform when they are simply not served. */
function choropleth(svg, values, opts = {}) {
  const { height = 420, fmt = compact, diverging = false, onClick,
    labelFmt = null } = opts;
  const w = frame(svg, height);
  const geo = DATA.geo;
  const [minLon, minLat, maxLon, maxLat] = geo.bbox;
  const midLat = ((minLat + maxLat) / 2) * Math.PI / 180;
  const kx = Math.cos(midLat);
  const spanX = (maxLon - minLon) * kx, spanY = maxLat - minLat;
  const pad = 12, legendH = 0;
  const scale = Math.min((w - pad * 2) / spanX,
                         (height - pad * 2 - legendH) / spanY);
  const offX = (w - spanX * scale) / 2, offY = (height - legendH - spanY * scale) / 2;
  const X = (lon) => offX + (lon - minLon) * kx * scale;
  const Y = (lat) => offY + (maxLat - lat) * scale;

  const present = geo.provinces.filter((p) => p.covered && values[p.name] !== undefined)
    .map((p) => values[p.name]);
  const lo = Math.min(...present), hi = Math.max(...present);
  const seq = ["--seq-100", "--seq-250", "--seq-400", "--seq-550", "--seq-700"]
    .map(cssv);
  const divNeg = [cssv("--series-2"), "#f0a882", "#f6d3c0"];
  const divPos = ["#b7d3f6", "#5598e7", cssv("--seq-550")];
  const midGray = document.documentElement.getAttribute("data-theme") === "dark"
    || (!document.documentElement.getAttribute("data-theme")
        && matchMedia("(prefers-color-scheme: dark)").matches) ? "#383835" : "#f0efec";

  function fill(v) {
    if (diverging) {
      const bound = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
      const t = v / bound;
      if (Math.abs(t) < 0.08) return midGray;
      const arm = t > 0 ? divPos : divNeg;
      return arm[Math.min(arm.length - 1, Math.floor(Math.abs(t) * arm.length))];
    }
    const t = (v - lo) / (hi - lo || 1);
    return seq[Math.min(seq.length - 1, Math.floor(t * seq.length))];
  }

  // Hatch for the no-coverage case: a texture, so it survives greyscale
  // printing and forced-colours mode where a pale fill would not.
  const defs = el("defs");
  const pat = el("pattern", {
    id: "nocover", width: 7, height: 7, patternUnits: "userSpaceOnUse",
    patternTransform: "rotate(45)",
  });
  pat.appendChild(el("rect", { width: 7, height: 7, fill: cssv("--surface-1") }));
  pat.appendChild(el("line", {
    x1: 0, y1: 0, x2: 0, y2: 7, stroke: cssv("--grid"), "stroke-width": 3,
  }));
  defs.appendChild(pat);
  svg.appendChild(defs);

  geo.provinces.forEach((p) => {
    const v = values[p.name];
    const has = p.covered && v !== undefined;
    const g = el("g");
    p.rings.forEach((ring) => {
      const d = ring.map((pt, i) => `${i ? "L" : "M"}${X(pt[0]).toFixed(1)},`
        + `${Y(pt[1]).toFixed(1)}`).join(" ") + " Z";
      g.appendChild(el("path", {
        d, fill: has ? fill(v) : "url(#nocover)",
        stroke: cssv("--surface-1"), "stroke-width": 1.5,
        "stroke-linejoin": "round",
      }));
    });
    hoverable(g, p.name, has
      ? [["Value", fmt(v)], ["Merchants", num(p.merchants)],
         ["Land area", num(p.areaSqKm) + " km2"]]
      : [["Coverage", "No merchants"], ["Land area", num(p.areaSqKm) + " km2"]],
      has && onClick ? () => onClick(p) : null);
    svg.appendChild(g);

    // Direct labels on the map itself - the relief rule, and a choropleth
    // that needs a colour-matching exercise to read is not doing its job.
    const cx = X(p.lon), cy = Y(p.lat);
    const t = has && !diverging ? (v - lo) / (hi - lo || 1) : 0;
    const onDark = has && !diverging ? t > 0.55
      : has && Math.abs(v) / (Math.max(Math.abs(lo), Math.abs(hi)) || 1) > 0.5;
    svg.appendChild(el("text", {
      x: cx, y: cy - 3, "text-anchor": "middle", "font-size": 10.5,
      "font-weight": 550,
      fill: onDark ? "#fff" : cssv("--text-primary"),
    }, p.code || p.name.slice(0, 3).toUpperCase()));
    svg.appendChild(el("text", {
      x: cx, y: cy + 10, "text-anchor": "middle", "font-size": 10,
      fill: onDark ? "rgba(255,255,255,.85)" : cssv("--text-secondary"),
    }, has ? (labelFmt || fmt)(v) : "no cover"));
  });
  return { lo, hi, diverging, fill, midGray };
}

function donut(svg, slices, opts = {}) {
  const { height = 210, fmt = num } = opts;
  const w = frame(svg, height);
  const cx = Math.min(w * 0.34, 100), cy = height / 2;
  const rOut = Math.min(cy - 12, 78), rIn = rOut * 0.6;
  const total = slices.reduce((a, s) => a + s.value, 0) || 1;
  let a0 = -Math.PI / 2;
  slices.forEach((s) => {
    const a1 = a0 + (s.value / total) * Math.PI * 2;
    const gap = 0.012; // 2px-equivalent surface gap between segments
    const [b0, b1] = [a0 + gap, a1 - gap];
    if (b1 > b0) {
      const large = b1 - b0 > Math.PI ? 1 : 0;
      const p = [
        `M ${cx + rOut * Math.cos(b0)} ${cy + rOut * Math.sin(b0)}`,
        `A ${rOut} ${rOut} 0 ${large} 1 ${cx + rOut * Math.cos(b1)} ${cy + rOut * Math.sin(b1)}`,
        `L ${cx + rIn * Math.cos(b1)} ${cy + rIn * Math.sin(b1)}`,
        `A ${rIn} ${rIn} 0 ${large} 0 ${cx + rIn * Math.cos(b0)} ${cy + rIn * Math.sin(b0)}`,
        "Z"].join(" ");
      const path = el("path", { d: p, fill: s.color });
      hoverable(path, s.label, [["Tickets", fmt(s.value)],
        ["Share", pct((s.value / total) * 100)]]);
      svg.appendChild(path);
    }
    a0 = a1;
  });
  svg.appendChild(el("text", {
    x: cx, y: cy - 4, "text-anchor": "middle", "font-size": 20, "font-weight": 650,
    fill: cssv("--text-primary"),
  }, num(total)));
  svg.appendChild(el("text", {
    x: cx, y: cy + 14, "text-anchor": "middle", class: "axislabel",
  }, "tickets"));
  // Direct labels beside the ring instead of a separate legend box.
  const lx = cx + rOut + 22;
  slices.forEach((s, i) => {
    const y = cy - (slices.length * 20) / 2 + i * 20 + 10;
    svg.appendChild(el("rect", { x: lx, y: y - 8, width: 10, height: 10, rx: 3, fill: s.color }));
    svg.appendChild(el("text", {
      x: lx + 16, y, class: "vallabel", fill: cssv("--text-secondary"),
    }, `${s.label}  ${num(s.value)} (${pct((s.value / total) * 100, 0)})`));
  });
}

/* ------------------------------------------------------------------ tables */
function renderTable(table, cols, rows, opts = {}) {
  const { sort, onSort, onRow, selectedKey } = opts;
  table.innerHTML = "";
  const thead = el2("thead"), tr = el2("tr");
  cols.forEach((c) => {
    const th = el2("th");
    th.textContent = c.label + (sort && sort.key === c.key ? (sort.dir === 1 ? " ↑" : " ↓") : "");
    if (onSort) th.addEventListener("click", () => onSort(c.key));
    tr.appendChild(th);
  });
  thead.appendChild(tr); table.appendChild(thead);
  const tbody = el2("tbody");
  rows.forEach((r) => {
    const row = el2("tr");
    if (onRow) { row.className = "clickable"; row.addEventListener("click", () => onRow(r)); }
    if (selectedKey && r._key === selectedKey) row.classList.add("selected");
    cols.forEach((c) => {
      const td = el2("td");
      const v = c.render ? c.render(r) : r[c.key];
      if (v instanceof Node) td.appendChild(v); else td.innerHTML = v;
      row.appendChild(td);
    });
    tbody.appendChild(row);
  });
  table.appendChild(tbody);
}
const el2 = (t) => document.createElement(t);
const pill = (cls, text) => `<span class="pill ${cls}">${text}</span>`;

/* ============================================================ page renders */
let A = null;

function renderExec() {
  const monthsSel = A.activeMonths;
  const last = monthsSel[monthsSel.length - 1], prev = monthsSel[monthsSel.length - 2];
  const mom = prev !== undefined && A.byMonth[prev]
    ? (A.byMonth[last] / A.byMonth[prev] - 1) * 100 : null;
  const redRate = A.vouchers ? (A.redeemed / A.vouchers) * 100 : 0;
  const avgRes = A.tickets ? A.resSum / A.tickets : 0;
  const breachPct = A.tickets ? (A.breaches / A.tickets) * 100 : 0;
  const basket = A.totalTx ? A.totalSales / A.totalTx : 0;

  tiles("execTiles", [
    { label: "Total sales", value: compact(A.totalSales), delta: mom,
      deltaText: mom === null ? "" : `${signed(mom)} vs prior month` },
    { label: "Transactions", value: num(A.totalTx), sub: `${zar(basket, 2)} average basket` },
    { label: "Redemption rate", value: pct(redRate), sub: `${num(A.vouchers)} vouchers sold` },
    { label: "Avg resolution", value: avgRes.toFixed(1) + "h", sub: `${num(A.tickets)} tickets` },
    { label: "SLA breach rate", value: pct(breachPct), sub: `${num(A.breaches)} breached`,
      status: breachPct > 20 ? "critical" : breachPct > 10 ? "warning" : "good" },
    { label: "Avg days to redeem", value: (A.redeemed ? A.daysSum / A.redeemed : 0).toFixed(2),
      sub: `${pct(A.redeemed ? (A.delayed / A.redeemed) * 100 : 0)} over 7 days` },
  ]);

  // Daily series with a 7-day moving average; the raw line alone is too noisy
  // to read a trend from at this density.
  const days = [], labels = [], ma = [];
  DATA.dates.forEach((d, i) => {
    if (!A.dateOK[i]) return;
    days.push(A.byDate[i]); labels.push(d.slice(5));
  });
  for (let i = 0; i < days.length; i++) {
    const s = Math.max(0, i - 6);
    ma.push(days.slice(s, i + 1).reduce((a, b) => a + b, 0) / (i - s + 1));
  }
  lineChart(document.getElementById("cExecTrend"), [
    { name: "Daily sales", color: cssv("--axis"), points: days, width: 1 },
    { name: "7-day average", color: seriesColor(0), points: ma, width: 2 },
  ], labels, { height: 240, xTickEvery: Math.ceil(labels.length / 7) });

  const regionRows = REGIONS.filter((r) => state.regions.has(r))
    .map((r) => ({ label: r, value: A.byRegion[r] }))
    .sort((a, b) => b.value - a.value);
  barsH(document.getElementById("cExecRegion"), regionRows, {
    color: seriesColor(0),
    tipFmt: compact,
  });

  const top = M.map((m, i) => ({ label: m.n, value: A.byMerch[i], idx: i }))
    .filter((r) => r.value > 0).sort((a, b) => b.value - a.value).slice(0, 10);
  barsH(document.getElementById("cExecTop"), top.map((r) => ({
    ...r,
    tip: [["Sales", zar(r.value)], ["Region", M[r.idx].r], ["Segment", M[r.idx].seg]],
  })), { color: seriesColor(0), onClick: (r) => openDrill(r.idx) });

  const vtSel = DATA.vt.map((v, i) => ({ v, i })).filter((o) => state.vtypes.has(o.v));
  legend("lExecVoucher", vtSel.map((o, k) => ({ name: o.v, color: seriesColor(k) })));
  barsV(document.getElementById("cExecVoucher"),
    A.activeMonths.map((mo) => ({
      label: MONTHS[mo].slice(0, 3),
      values: vtSel.map((o) => A.vtMonth[o.i][mo]),
    })),
    vtSel.map((o, k) => ({ name: o.v, color: seriesColor(k) })),
    { height: 250, stacked: true });

  const redSeries = A.activeMonths.map((mo) => A.soldMonth[mo]
    ? (A.redMonth[mo] / A.soldMonth[mo]) * 100 : null);
  lineChart(document.getElementById("cExecRedemption"),
    [{ name: "Redemption rate", color: seriesColor(2), points: redSeries }],
    A.activeMonths.map((mo) => MONTHS[mo].slice(0, 3)),
    { height: 210, fmt: (v) => v.toFixed(0) + "%", yZero: false, area: true });

  const mom3 = REGIONS.filter((r) => state.regions.has(r)).map((r) => {
    const s = A.activeMonths.map((mo) => A.regionMonth[r][mo]);
    if (s.length < 4) return { label: r, value: 0 };
    const lastV = s[s.length - 1];
    const base = s.slice(-4, -1).reduce((a, b) => a + b, 0) / 3;
    return { label: r, value: base ? (lastV / base - 1) * 100 : 0 };
  }).sort((a, b) => a.value - b.value);
  barsH(document.getElementById("cExecMomentum"), mom3.map((r) => ({
    ...r,
    color: r.value < 0 ? cssv(STATUS.critical) : cssv(STATUS.good),
    tip: [["Momentum", signed(r.value)]],
  })), { fmt: (v) => signed(v) });

  const ranked = M.map((m, i) => A.byMerch[i]).filter((v) => v > 0)
    .sort((a, b) => b - a);
  const tot = ranked.reduce((a, b) => a + b, 0) || 1;
  let acc = 0;
  const cum = ranked.map((v) => { acc += v; return (acc / tot) * 100; });
  lineChart(document.getElementById("cExecPareto"),
    [{ name: "Cumulative share", color: seriesColor(1), points: cum }],
    ranked.map((_, i) => String(i + 1)),
    { height: 210, fmt: (v) => v.toFixed(0) + "%", xTickEvery: 5, area: true });
}

function renderMerchant() {
  const rows = M.map((m, i) => {
    const sales = A.byMerch[i], tx = A.txByMerch[i];
    const red = A.merchRed[i];
    const tk = A.tkByMerch[i];
    return {
      _key: m.k, idx: i, name: m.n, region: m.r, channel: m.c, seg: m.seg,
      tier: m.tier, hs: m.hs, flag: m.flag, mom: m.mom, slope: m.slope,
      sales, tx, basket: tx ? sales / tx : 0,
      redrate: red.n ? (red.rd / red.n) * 100 : 0,
      days: red.rd ? red.sd / red.rd : 0,
      tickets: tk, per1k: tx ? (tk / tx) * 1000 : 0,
      res: tk ? A.resByMerch[i] / tk : 0,
      breach: tk ? (A.brByMerch[i] / tk) * 100 : 0,
      share: A.totalSales ? (sales / A.totalSales) * 100 : 0,
    };
  }).filter((r) => A.merchOK[r.idx]);

  const ranked = [...rows].sort((a, b) => b.sales - a.sales);
  barsH(document.getElementById("cMerchTop"), ranked.slice(0, 5).map((r) => ({
    label: r.name, value: r.sales, idx: r.idx,
    tip: [["Sales", zar(r.sales)], ["Share", pct(r.share)], ["Region", r.region]],
  })), { color: seriesColor(0), onClick: (r) => openDrill(r.idx) });
  barsH(document.getElementById("cMerchBottom"), ranked.slice(-5).reverse().map((r) => ({
    label: r.name, value: r.sales, idx: r.idx,
    tip: [["Sales", zar(r.sales)], ["Share", pct(r.share)], ["Region", r.region]],
  })), { color: seriesColor(1), onClick: (r) => openDrill(r.idx) });

  legend("lMerchSeg", segNames.map((s, i) => ({ name: s, color: seriesColor(i) })));
  scatter(document.getElementById("cMerchScatter"), rows.map((r) => ({
    x: r.sales, y: r.slope, r: r.tickets, color: segColor(r.seg), label: r.name,
    idx: r.idx,
    tip: [["Sales", zar(r.sales)], ["Growth slope", signed(r.slope)],
      ["Tickets", num(r.tickets)], ["Segment", r.seg], ["Health", r.hs.toFixed(0)]],
  })), {
    height: 320, xLabel: "Total sales value (ZAR)",
    yLabel: "Monthly growth slope (% of own mean)",
    fmtY: (v) => v.toFixed(0) + "%",
    onClick: (p) => openDrill(p.idx),
  });

  const vtRows = DATA.vt.map((v, i) => ({ v, i })).filter((o) => state.vtypes.has(o.v))
    .map((o) => {
      const a = A.vtRed[o.i];
      return {
        label: o.v, value: a.n ? (a.rd / a.n) * 100 : 0,
        sales: A.byVt[o.i],
        tip: [["Redemption rate", pct(a.n ? (a.rd / a.n) * 100 : 0)],
          ["Vouchers", num(a.n)], ["Sales value", zar(A.byVt[o.i])],
          ["Avg days to redeem", (a.rd ? a.sd / a.rd : 0).toFixed(2)],
          ["Delayed over 7 days", pct(a.rd ? (a.dl / a.rd) * 100 : 0)]],
      };
    }).sort((a, b) => b.value - a.value);
  barsH(document.getElementById("cMerchVoucher"), vtRows,
    { color: seriesColor(2), fmt: (v) => pct(v) });

  const cols = [
    { key: "name", label: "Merchant" },
    { key: "region", label: "Region" },
    { key: "seg", label: "Segment" },
    { key: "sales", label: "Sales", render: (r) => zar(r.sales) },
    { key: "share", label: "Share", render: (r) => pct(r.share) },
    { key: "tx", label: "Transactions", render: (r) => num(r.tx) },
    { key: "basket", label: "Avg basket", render: (r) => zar(r.basket, 2) },
    { key: "mom", label: "MoM", render: (r) => `<span class="${r.mom < 0 ? "down" : "up"}">${signed(r.mom)}</span>` },
    { key: "redrate", label: "Redemption", render: (r) => pct(r.redrate) },
    { key: "tickets", label: "Tickets", render: (r) => num(r.tickets) },
    { key: "per1k", label: "Tickets / 1k tx", render: (r) => r.per1k.toFixed(2) },
    { key: "hs", label: "Health", render: (r) => pill(tierClass(r.tier), r.hs.toFixed(0)) },
  ];
  const s = state.sortMerch;
  const sorted = [...rows].sort((a, b) => {
    const x = a[s.key], y = b[s.key];
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * s.dir;
  });
  renderTable(document.getElementById("tMerchants"), cols, sorted, {
    sort: s,
    onSort: (k) => {
      state.sortMerch = { key: k, dir: s.key === k ? -s.dir : -1 };
      renderMerchant();
    },
    onRow: (r) => openDrill(r.idx),
  });
}

const tierClass = (t) => t === "Healthy" ? "good" : t === "Watch" ? "warning"
  : t === "At risk" ? "serious" : "critical";

function renderOps() {
  const avgRes = A.tickets ? A.resSum / A.tickets : 0;
  const breachPct = A.tickets ? (A.breaches / A.tickets) * 100 : 0;
  tiles("opsTiles", [
    { label: "Tickets raised", value: num(A.tickets) },
    { label: "Avg resolution", value: avgRes.toFixed(1) + "h" },
    { label: "SLA breach rate", value: pct(breachPct),
      status: breachPct > 20 ? "critical" : "warning" },
    { label: "Breached tickets", value: num(A.breaches) },
    { label: "Still open", value: num(A.open),
      sub: pct(A.tickets ? (A.open / A.tickets) * 100 : 0) + " of book" },
    { label: "Tickets per 1k tx", value: (A.totalTx ? (A.tickets / A.totalTx) * 1000 : 0).toFixed(2) },
  ]);

  const prioRows = DATA.prio.map((p, i) => ({ p, i, a: A.tkByPrio[i] }))
    .filter((o) => o.a.n > 0);
  legend("lOpsSla", [
    { name: "Average resolution hours", color: seriesColor(1) },
    { name: "SLA target hours", color: seriesColor(0) },
  ]);
  barsV(document.getElementById("cOpsSla"),
    prioRows.map((o) => ({
      label: o.p.n, values: [o.a.n ? o.a.res / o.a.n : 0, o.p.sla],
    })),
    [{ name: "Average resolution hours", color: seriesColor(1) },
     { name: "SLA target hours", color: seriesColor(0) }],
    { height: 250, stacked: false, fmt: (v) => v.toFixed(0) + "h" });
  renderTable(document.getElementById("tOpsSla"), [
    { key: "p", label: "Priority" },
    { key: "n", label: "Tickets", render: (r) => num(r.n) },
    { key: "sla", label: "SLA target", render: (r) => r.sla + "h" },
    { key: "res", label: "Avg resolution", render: (r) => r.res.toFixed(1) + "h" },
    { key: "br", label: "Breach rate", render: (r) => pill(r.br > 50 ? "critical" : r.br > 10 ? "warning" : "good", pct(r.br)) },
  ], prioRows.map((o) => ({
    p: o.p.n, n: o.a.n, sla: o.p.sla, res: o.a.n ? o.a.res / o.a.n : 0,
    br: o.a.n ? (o.a.br / o.a.n) * 100 : 0,
  })));

  lineChart(document.getElementById("cOpsTrend"),
    [{ name: "Tickets", color: seriesColor(1),
       points: A.activeMonths.map((mo) => A.tkByMonth[mo]) }],
    A.activeMonths.map((mo) => MONTHS[mo].slice(0, 3)),
    { height: 230, fmt: (v) => num(v), area: true });

  // Status counts need a pass over the ticket rows under the current filter.
  const st = { Closed: 0, Open: 0, Escalated: 0, "Pending Merchant": 0 };
  const T = DATA.tick;
  for (let i = 0; i < T.d.length; i++) {
    if (!A.dateOK[T.d[i]] || !A.merchOK[T.m[i]]) continue;
    st[T.op[i] ? "_open" : "Closed"] = (st[T.op[i] ? "_open" : "Closed"] || 0) + 1;
  }
  donut(document.getElementById("cOpsStatus"), [
    { label: "Closed", value: st.Closed || 0, color: seriesColor(0) },
    { label: "Still open", value: st._open || 0, color: seriesColor(1) },
  ], { height: 210 });

  const typeRows = DATA.tt.map((t, i) => ({
    label: t, value: A.tkByType[i].n,
    tip: [["Tickets", num(A.tkByType[i].n)],
      ["Avg resolution", (A.tkByType[i].n ? A.tkByType[i].res / A.tkByType[i].n : 0).toFixed(1) + "h"],
      ["Breach rate", pct(A.tkByType[i].n ? (A.tkByType[i].br / A.tkByType[i].n) * 100 : 0)],
      ["Category", DATA.ttCat[t]]],
  })).filter((r) => r.value > 0).sort((a, b) => b.value - a.value);
  barsH(document.getElementById("cOpsTypes"), typeRows, { color: seriesColor(1), fmt: num });

  const lagRegions = REGIONS.filter((r) => state.regions.has(r));
  const lagVts = DATA.vt.filter((v) => state.vtypes.has(v));
  const lagMonths = A.activeMonths.map((mo) => MONTHS[mo]);
  const grid = lagRegions.map((r) => lagVts.map((v) => {
    const rows = DATA.lag.filter((x) => x.Region === r && x.VoucherTypeKey === v
      && lagMonths.includes(x.MonthYear));
    if (!rows.length) return null;
    const n = rows.reduce((a, b) => a + b.Vouchers, 0);
    return rows.reduce((a, b) => a + b.AvgDays * b.Vouchers, 0) / (n || 1);
  }));
  heatgrid(document.getElementById("cOpsLag"), lagRegions, lagVts, grid, {
    fmt: (v) => v.toFixed(1),
    onHover: (i, j, v) => [["Avg days to redeem", v.toFixed(2)],
      ["Region", lagRegions[i]], ["Voucher type", lagVts[j]]],
  });

  const opsRows = M.map((m, i) => ({
    _key: m.k, idx: i, name: m.n, region: m.r, tickets: A.tkByMerch[i],
    per1k: A.txByMerch[i] ? (A.tkByMerch[i] / A.txByMerch[i]) * 1000 : 0,
    res: A.tkByMerch[i] ? A.resByMerch[i] / A.tkByMerch[i] : 0,
    breach: A.tkByMerch[i] ? (A.brByMerch[i] / A.tkByMerch[i]) * 100 : 0,
    breaches: A.brByMerch[i], mom: m.mom,
  })).filter((r) => A.merchOK[r.idx] && r.tickets > 0);
  const so = state.sortOps;
  opsRows.sort((a, b) => {
    const x = a[so.key], y = b[so.key];
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * so.dir;
  });
  renderTable(document.getElementById("tOps"), [
    { key: "name", label: "Merchant" },
    { key: "region", label: "Region" },
    { key: "tickets", label: "Tickets", render: (r) => num(r.tickets) },
    { key: "per1k", label: "Per 1k transactions", render: (r) => r.per1k.toFixed(2) },
    { key: "res", label: "Avg resolution", render: (r) => r.res.toFixed(1) + "h" },
    { key: "breaches", label: "Breaches", render: (r) => num(r.breaches) },
    { key: "breach", label: "Breach rate", render: (r) => pill(r.breach > 40 ? "critical" : r.breach > 20 ? "warning" : "good", pct(r.breach)) },
    { key: "mom", label: "Sales MoM", render: (r) => `<span class="${r.mom < 0 ? "down" : "up"}">${signed(r.mom)}</span>` },
  ], opsRows, {
    sort: so,
    onSort: (k) => { state.sortOps = { key: k, dir: so.key === k ? -so.dir : -1 }; renderOps(); },
    onRow: (r) => openDrill(r.idx),
  });
}

/* ------------------------------------------------------- geo intelligence */
const GEO_METRICS = [
  { key: "sales", label: "Total sales", fmt: compact, short: compact },
  { key: "transactions", label: "Transactions", fmt: num, short: (v) => num(Math.round(v / 1000)) + "k" },
  { key: "merchants", label: "Merchant count", fmt: num, short: num },
  { key: "redemption", label: "Redemption rate", fmt: (v) => pct(v), short: (v) => pct(v, 0) },
  { key: "per1k", label: "Tickets per 1k transactions", fmt: (v) => v.toFixed(2), short: (v) => v.toFixed(1) },
  { key: "breach", label: "SLA breach rate", fmt: (v) => pct(v), short: (v) => pct(v, 0) },
  { key: "density", label: "Sales per 1,000 km²", fmt: compact, short: compact },
  { key: "momentum", label: "Momentum (latest vs prior 3 months)", fmt: (v) => signed(v),
    short: (v) => signed(v, 0), diverging: true },
  { key: "health", label: "Average merchant health score", fmt: (v) => v.toFixed(0), short: (v) => v.toFixed(0) },
];
let geoMetricKey = "sales";

function geoStats() {
  const byProv = {};
  DATA.geo.provinces.forEach((p) => (byProv[p.name] = {
    name: p.name, area: p.areaSqKm, merchants: 0, sales: 0, transactions: 0,
    vouchers: 0, redeemed: 0, tickets: 0, breaches: 0, health: 0, covered: p.covered,
    series: new Float64Array(NMONTH),
  }));
  M.forEach((m, i) => {
    if (!A.merchOK[i] || !byProv[m.r]) return;
    const s = byProv[m.r];
    s.merchants++; s.sales += A.byMerch[i]; s.transactions += A.txByMerch[i];
    s.vouchers += A.merchRed[i].n; s.redeemed += A.merchRed[i].rd;
    s.tickets += A.tkByMerch[i]; s.breaches += A.brByMerch[i];
    s.health += m.hs;
    A.activeMonths.forEach((mo) => (s.series[mo] += A.merchMonth[i][mo]));
  });
  Object.values(byProv).forEach((s) => {
    s.redemption = s.vouchers ? (s.redeemed / s.vouchers) * 100 : 0;
    s.per1k = s.transactions ? (s.tickets / s.transactions) * 1000 : 0;
    s.breach = s.tickets ? (s.breaches / s.tickets) * 100 : 0;
    s.density = s.area ? s.sales / (s.area / 1000) : 0;
    s.health = s.merchants ? s.health / s.merchants : 0;
    const vals = A.activeMonths.map((mo) => s.series[mo]);
    const base = vals.length >= 4
      ? vals.slice(-4, -1).reduce((a, b) => a + b, 0) / 3 : 0;
    s.momentum = base ? (vals[vals.length - 1] / base - 1) * 100 : 0;
    s.salesShare = A.totalSales ? (s.sales / A.totalSales) * 100 : 0;
    s.merchShare = (s.merchants / M.filter((m, i) => A.merchOK[i]).length) * 100;
  });
  return byProv;
}

function renderGeo() {
  const stats = geoStats();
  const covered = Object.values(stats).filter((s) => s.covered && s.merchants > 0);
  const uncovered = DATA.geo.provinces.filter(
    (p) => !covered.some((c) => c.name === p.name));
  const uncoveredArea = uncovered.reduce((a, p) => a + p.areaSqKm, 0);
  const totalArea = DATA.geo.provinces.reduce((a, p) => a + p.areaSqKm, 0);

  tiles("geoTiles", [
    { label: "Provinces served", value: `${covered.length} of ${DATA.geo.provinces.length}`,
      sub: `${uncovered.map((p) => p.name).join(", ")} unserved`,
      status: covered.length < DATA.geo.provinces.length ? "warning" : "good" },
    { label: "Land area unserved", value: pct((uncoveredArea / totalArea) * 100, 0),
      sub: `${num(uncoveredArea)} km² with no merchant` },
    { label: "Top province share", value: pct(Math.max(...covered.map((s) => s.salesShare))),
      sub: covered.sort((a, b) => b.sales - a.sales)[0].name + " of national sales" },
    { label: "Weakest momentum",
      value: signed(Math.min(...covered.map((s) => s.momentum))),
      sub: covered.slice().sort((a, b) => a.momentum - b.momentum)[0].name,
      status: Math.min(...covered.map((s) => s.momentum)) < 0 ? "serious" : "good" },
  ]);

  const sel = document.getElementById("geoMetric");
  if (!sel.options.length) {
    GEO_METRICS.forEach((m) => sel.appendChild(new Option(m.label, m.key)));
    sel.addEventListener("change", () => { geoMetricKey = sel.value; renderGeo(); });
  }
  sel.value = geoMetricKey;
  const metric = GEO_METRICS.find((m) => m.key === geoMetricKey);
  document.getElementById("geoMetricNote").textContent =
    metric.diverging ? "diverging scale, zero is neutral" : "sequential scale, one hue";

  const values = {};
  covered.forEach((s) => (values[s.name] = s[metric.key]));
  const scale = choropleth(document.getElementById("cMap"), values, {
    height: 430, fmt: metric.fmt, labelFmt: metric.short,
    diverging: !!metric.diverging,
    onClick: (p) => {
      // Clicking a province filters the whole report to it.
      state.regions.clear(); state.regions.add(p.name);
      refresh();
    },
  });
  const rampItems = metric.diverging
    ? [{ name: "Below prior average", color: cssv("--series-2") },
       { name: "Around flat", color: scale.midGray },
       { name: "Above prior average", color: cssv("--seq-550") }]
    : [{ name: `Low ${metric.fmt(scale.lo)}`, color: cssv("--seq-100") },
       { name: metric.fmt((scale.lo + scale.hi) / 2), color: cssv("--seq-400") },
       { name: `High ${metric.fmt(scale.hi)}`, color: cssv("--seq-700") }];
  legend("lMap", rampItems.concat([{ name: "No merchant coverage", color: cssv("--grid") }]));

  barsH(document.getElementById("cGeoCoverage"),
    DATA.geo.provinces.map((p) => ({
      label: p.name,
      value: stats[p.name].merchants,
      color: stats[p.name].merchants ? seriesColor(0) : cssv("--grid"),
      tip: [["Merchants", num(stats[p.name].merchants)],
        ["Land area", num(p.areaSqKm) + " km2"],
        ["Sales", compact(stats[p.name].sales)]],
    })).sort((a, b) => b.value - a.value),
    { fmt: (v) => num(v) });

  // Share of sales against share of merchants: above the diagonal means the
  // province earns more than its headcount implies.
  scatter(document.getElementById("cGeoConcentration"), covered.map((s) => ({
    x: s.merchShare, y: s.salesShare, r: s.merchants, color: seriesColor(0),
    label: s.name,
    tip: [["Share of sales", pct(s.salesShare)],
      ["Share of merchants", pct(s.merchShare)],
      ["Sales per merchant", compact(s.sales / s.merchants)]],
  })), {
    height: 250, xLabel: "Share of merchant base", yLabel: "Share of sales",
    fmtX: (v) => pct(v, 0), fmtY: (v) => pct(v, 0),
  });

  barsH(document.getElementById("cGeoMomentum"),
    covered.map((s) => ({
      label: s.name, value: s.momentum,
      color: s.momentum < 0 ? cssv(STATUS.critical) : cssv(STATUS.good),
      tip: [["Momentum", signed(s.momentum)], ["Latest month", compact(
        s.series[A.activeMonths[A.activeMonths.length - 1]])]],
    })).sort((a, b) => a.value - b.value),
    { fmt: (v) => signed(v) });

  barsH(document.getElementById("cGeoOps"),
    covered.map((s) => ({
      label: s.name, value: s.per1k, color: seriesColor(1),
      tip: [["Tickets per 1k tx", s.per1k.toFixed(2)],
        ["Tickets", num(s.tickets)], ["SLA breach rate", pct(s.breach)]],
    })).sort((a, b) => b.value - a.value),
    { fmt: (v) => v.toFixed(2) });

  renderTable(document.getElementById("tGeo"), [
    { key: "name", label: "Province" },
    { key: "merchants", label: "Merchants",
      render: (r) => r.merchants || pill("neutral", "none") },
    { key: "sales", label: "Sales", render: (r) => r.merchants ? zar(r.sales) : "&ndash;" },
    { key: "salesShare", label: "Share", render: (r) => r.merchants ? pct(r.salesShare) : "&ndash;" },
    { key: "area", label: "Land area", render: (r) => num(r.area) + " km&sup2;" },
    { key: "density", label: "Sales / 1k km&sup2;", render: (r) => r.merchants ? compact(r.density) : "&ndash;" },
    { key: "redemption", label: "Redemption", render: (r) => r.merchants ? pct(r.redemption) : "&ndash;" },
    { key: "per1k", label: "Tickets / 1k tx", render: (r) => r.merchants ? r.per1k.toFixed(2) : "&ndash;" },
    { key: "breach", label: "SLA breach", render: (r) => r.merchants ? pct(r.breach) : "&ndash;" },
    { key: "momentum", label: "Momentum",
      render: (r) => r.merchants
        ? `<span class="${r.momentum < 0 ? "down" : "up"}">${signed(r.momentum)}</span>` : "&ndash;" },
    { key: "health", label: "Avg health", render: (r) => r.merchants ? r.health.toFixed(0) : "&ndash;" },
  ], Object.values(stats).sort((a, b) => b.sales - a.sales));
}

function renderAI() {
  const ml = DATA.ml;
  tiles("aiTiles", [
    { label: "Forecast next 30 days", value: compact(ml.forecast.reduce((a, b) => a + b.f, 0)),
      sub: `${ml.selected.split("(")[0].trim()}, MAPE ${ml.mape}%` },
    { label: "Redemption model AUC", value: ml.redeemAuc.toFixed(3),
      sub: "held out on June-July" },
    { label: "SLA breach model AUC", value: ml.slaAuc.toFixed(3), sub: "5-fold cross-validated" },
    { label: "Expected non-redemption", value: compact(ml.breakage),
      sub: "voucher value unlikely to be redeemed", status: "warning" },
  ]);

  // Actual, backtest and forward projection on one scale.
  const bt = ml.backtest, fc = ml.forecast;
  const histDates = [], hist = [];
  DATA.dates.forEach((d, i) => { histDates.push(d.slice(5)); hist.push(A.byDate[i]); });
  const labels = histDates.concat(fc.map((f) => f.d.slice(5)));
  const actual = hist.concat(fc.map(() => null));
  const back = DATA.dates.map((d) => {
    const hit = bt.find((b) => b.Date === d);
    return hit ? hit.Predicted : null;
  }).concat(fc.map(() => null));
  const fwd = DATA.dates.map((d, i) => (i === DATA.dates.length - 1 ? hist[i] : null))
    .concat(fc.map((f) => f.f));
  const bands = fc.map((f, i) => ({ i: DATA.dates.length + i, lo: f.lo, hi: f.hi }));
  document.getElementById("fcSub").textContent =
    `${ml.selected} selected from ${Object.keys(ml.candidates).length} candidates by held-out error`;
  legend("lFc", [
    { name: "Actual", color: cssv("--axis") },
    { name: "Backtest prediction", color: seriesColor(2) },
    { name: "Forward forecast", color: seriesColor(1) },
  ]);
  lineChart(document.getElementById("cForecast"), [
    { name: "Actual", color: cssv("--axis"), points: actual, width: 1.5 },
    { name: "Backtest prediction", color: seriesColor(2), points: back, width: 2, dash: "5 3" },
    { name: "Forward forecast", color: seriesColor(1), points: fwd, width: 2 },
  ], labels, { height: 280, bands, xTickEvery: Math.ceil(labels.length / 8), yZero: false });
  document.getElementById("fcNote").textContent =
    `Backtest on the last 28 days: MAPE ${ml.mape}% against a seasonal-naive `
    + `benchmark of ${ml.naiveMape}%. Shaded band is the 95% interval, widened `
    + `with horizon. Candidates: `
    + Object.entries(ml.candidates).map(([k, v]) => `${k} ${v}%`).join("; ") + ".";

  legend("lSeg", ml.segments.map((s, i) => ({
    name: `${s.Segment} (${s.Count})`, color: seriesColor(i),
  })));
  scatter(document.getElementById("cSegments"), M.filter((m, i) => A.merchOK[i])
    .map((m) => ({
      x: m.p1, y: m.p2, r: Math.max(1, m.hs), color: segColor(m.seg), label: m.n,
      idx: M.indexOf(m),
      tip: [["Segment", m.seg], ["Health score", m.hs.toFixed(0)],
        ["Risk tier", m.tier], ["Growth slope", signed(m.slope)],
        ["Target attainment", pct(m.att)]],
    })), {
    height: 320, xLabel: `Principal component 1`,
    yLabel: "Principal component 2",
    fmtX: (v) => v.toFixed(1), fmtY: (v) => v.toFixed(1),
    onClick: (p) => openDrill(p.idx),
  });

  const health = M.map((m, i) => ({ m, i })).filter((o) => A.merchOK[o.i])
    .sort((a, b) => a.m.hs - b.m.hs).slice(0, 12);
  barsH(document.getElementById("cHealth"), health.map((o) => ({
    label: o.m.n, value: o.m.hs, idx: o.i,
    color: cssv(STATUS[tierClass(o.m.tier)]),
    tip: [["Health score", o.m.hs.toFixed(1)], ["Risk tier", o.m.tier],
      ["Segment", o.m.seg], ["Growth slope", signed(o.m.slope)]],
  })), { fmt: (v) => v.toFixed(0), onClick: (r) => openDrill(r.idx) });

  renderTable(document.getElementById("tPerf"), [
    { key: "Model", label: "Model" },
    { key: "Metric", label: "Metric" },
    { key: "Value", label: "Value", render: (r) => Number(r.Value).toFixed(4) },
    { key: "HoldoutMethod", label: "Holdout" },
    { key: "Note", label: "Note" },
  ], ml.performance);

  const impByModel = {};
  ml.importance.forEach((r) => {
    (impByModel[r.Model] = impByModel[r.Model] || []).push(r);
  });
  const impRows = [];
  Object.entries(impByModel).forEach(([model, rows]) => {
    rows.slice(0, 4).forEach((r) => impRows.push({
      label: `${r.Feature}  (${model.split(" ")[0]})`,
      value: r.ImportanceAUCDrop,
      color: seriesColor(Object.keys(impByModel).indexOf(model)),
      tip: [["Model", model], ["Feature", r.Feature],
        ["AUC drop when shuffled", r.ImportanceAUCDrop.toFixed(5)]],
    }));
  });
  barsH(document.getElementById("cImportance"), impRows,
    { fmt: (v) => v.toFixed(4) });

  renderTable(document.getElementById("tAnomalies"), [
    { key: "Date", label: "Date" },
    { key: "Merchant", label: "Entity" },
    { key: "Measure", label: "Measure" },
    { key: "ActualValue", label: "Actual", render: (r) => num(r.ActualValue, 1) },
    { key: "ExpectedValue", label: "Expected", render: (r) => num(r.ExpectedValue, 1) },
    { key: "DeviationPct", label: "Deviation", render: (r) => signed(r.DeviationPct, 0) },
    { key: "Score", label: "Score", render: (r) => `${Number(r.Score).toFixed(1)}<span class="axislabel"> ${r.ScoreType === "Robust z" ? "z" : "%"}</span>` },
    { key: "Severity", label: "Severity", render: (r) => pill(r.Severity === "High" ? "critical" : r.Severity === "Medium" ? "warning" : "neutral", r.Severity) },
  ], [...DATA.anomalies].sort((a, b) => {
    const rank = { High: 0, Medium: 1, Low: 2 };
    return rank[a.Severity] - rank[b.Severity] || Math.abs(b.Score) - Math.abs(a.Score);
  }));

  renderTable(document.getElementById("tRisk"), [
    { key: "Merchant", label: "Merchant" },
    { key: "VoucherTypeKey", label: "Voucher type" },
    { key: "Vouchers", label: "Vouchers", render: (r) => num(r.Vouchers) },
    { key: "PredictedRedemptionRate", label: "Predicted redemption", render: (r) => pct(r.PredictedRedemptionRate) },
    { key: "ActualRedemptionRate", label: "Actual", render: (r) => pct(r.ActualRedemptionRate) },
    { key: "ExpectedUnredeemedValue", label: "Exposure", render: (r) => zar(r.ExpectedUnredeemedValue) },
  ], ml.voucherRisk);
}

/* --------------------------------------------------------------- tiles/legend */
function tiles(id, items) {
  const host = document.getElementById(id);
  host.innerHTML = "";
  items.forEach((t) => {
    const d = el2("div"); d.className = "card tile";
    const cls = t.delta === undefined || t.delta === null ? ""
      : t.delta > 0.5 ? "up" : t.delta < -0.5 ? "down" : "flat";
    d.innerHTML = `<div class="label">${t.label}</div>
      <div class="value">${t.value}</div>
      <div class="delta ${cls}">${t.deltaText || t.sub || ""}</div>`;
    if (t.status) {
      d.querySelector(".delta").insertAdjacentHTML("afterbegin",
        pill(t.status, t.status === "good" ? "ok" : t.status) + " ");
    }
    host.appendChild(d);
  });
}

function legend(id, items) {
  const host = document.getElementById(id);
  if (!host) return;
  host.innerHTML = items.map((i) =>
    `<span class="item"><span class="swatch" style="background:${i.color}"></span>${i.name}</span>`
  ).join("");
}

/* ---------------------------------------------------------- drill-through */
function openDrill(idx) {
  const m = M[idx];
  const monthVals = A.activeMonths.map((mo) => A.merchMonth[idx][mo]);
  const red = A.merchRed[idx];
  const tk = A.tkByMerch[idx];
  const body = document.getElementById("drillBody");
  const anomalies = DATA.anomalies.filter((a) => a.MerchantKey === m.k);

  body.innerHTML = `
    <h2>${m.n}</h2>
    <div class="meta">${m.r} &middot; ${m.c} &middot; ${m.st} &middot; account manager ${m.am}
      &middot; ${pill(tierClass(m.tier), m.tier + " " + m.hs.toFixed(0))}</div>
    ${m.nar ? `<div class="narrative"><strong>Auto-generated narrative.</strong> ${m.nar}</div>` : ""}
    <div class="minigrid">
      <div class="mini"><div class="label">Sales</div><div class="value">${compact(A.byMerch[idx])}</div></div>
      <div class="mini"><div class="label">Transactions</div><div class="value">${num(A.txByMerch[idx])}</div></div>
      <div class="mini"><div class="label">Avg basket</div><div class="value">${zar(A.txByMerch[idx] ? A.byMerch[idx] / A.txByMerch[idx] : 0, 2)}</div></div>
      <div class="mini"><div class="label">Redemption</div><div class="value">${pct(red.n ? (red.rd / red.n) * 100 : 0)}</div></div>
      <div class="mini"><div class="label">Tickets</div><div class="value">${num(tk)}</div></div>
      <div class="mini"><div class="label">Breach rate</div><div class="value">${pct(tk ? (A.brByMerch[idx] / tk) * 100 : 0)}</div></div>
      <div class="mini"><div class="label">Month on month</div><div class="value ${m.mom < 0 ? "down" : "up"}">${signed(m.mom)}</div></div>
      <div class="mini"><div class="label">Segment</div><div class="value" style="font-size:13px">${m.seg}</div></div>
      <div class="mini"><div class="label">Next 30 days</div><div class="value">${compact(m.fc)}</div></div>
    </div>
    <h3 style="font-size:13px;margin-bottom:6px">Monthly sales</h3>
    <div class="chartwrap"><svg class="chart" id="dTrend"></svg></div>
    <h3 style="font-size:13px;margin:16px 0 6px">Sales by voucher type</h3>
    <div class="chartwrap"><svg class="chart" id="dVoucher"></svg></div>
    ${anomalies.length ? `<h3 style="font-size:13px;margin:16px 0 6px">Anomalies detected</h3>
      <div class="tablewrap"><table id="dAnom"></table></div>` : ""}
  `;

  barsV(document.getElementById("dTrend"),
    A.activeMonths.map((mo, k) => ({ label: MONTHS[mo].slice(0, 3), values: [monthVals[k]] })),
    [{ name: "Sales", color: seriesColor(0) }],
    { height: 190, stacked: false });

  const vtVals = DATA.vt.map((v, i) => ({ v, i })).filter((o) => state.vtypes.has(o.v))
    .map((o) => {
      let sum = 0;
      const S = DATA.sales;
      for (let k = 0; k < S.d.length; k++) {
        if (S.m[k] === idx && S.v[k] === o.i && A.dateOK[S.d[k]]) sum += S.s[k];
      }
      return { label: o.v, value: sum };
    }).sort((a, b) => b.value - a.value);
  barsH(document.getElementById("dVoucher"), vtVals, { color: seriesColor(2) });

  if (anomalies.length) {
    renderTable(document.getElementById("dAnom"), [
      { key: "Date", label: "Date" },
      { key: "Measure", label: "Measure" },
      { key: "ActualValue", label: "Actual", render: (r) => num(r.ActualValue, 1) },
      { key: "ExpectedValue", label: "Expected", render: (r) => num(r.ExpectedValue, 1) },
      { key: "Severity", label: "Severity", render: (r) => pill(r.Severity === "High" ? "critical" : r.Severity === "Medium" ? "warning" : "neutral", r.Severity) },
    ], anomalies);
  }

  document.getElementById("drill").classList.add("open");
  document.getElementById("drill").setAttribute("aria-hidden", "false");
  document.getElementById("backdrop").classList.add("open");
}
function closeDrill() {
  document.getElementById("drill").classList.remove("open");
  document.getElementById("drill").setAttribute("aria-hidden", "true");
  document.getElementById("backdrop").classList.remove("open");
}

/* --------------------------------------------------------------- narrative */
function renderNotes() {
  const c = DATA.correlation, con = DATA.concentration, ml = DATA.ml;
  const top = M.map((m, i) => ({ m, v: A.byMerch[i] })).sort((a, b) => b.v - a.v);
  const bestVt = DATA.vt.map((v, i) => ({
    v, rate: A.vtRed[i].n ? (A.vtRed[i].rd / A.vtRed[i].n) * 100 : 0,
  })).sort((a, b) => b.rate - a.rate);
  const worstRegion = REGIONS.map((r) => {
    const s = A.activeMonths.map((mo) => A.regionMonth[r][mo]);
    const base = s.slice(-4, -1).reduce((a, b) => a + b, 0) / 3;
    return { r, mom: base ? (s[s.length - 1] / base - 1) * 100 : 0 };
  }).sort((a, b) => a.mom - b.mom)[0];
  const declining = M.map((m, i) => ({ m, i })).filter((o) => o.m.mom < -10)
    .sort((a, b) => a.m.mom - b.m.mom);
  const prioBad = DATA.prio.map((p, i) => ({
    p, res: A.tkByPrio[i].n ? A.tkByPrio[i].res / A.tkByPrio[i].n : 0,
    br: A.tkByPrio[i].n ? (A.tkByPrio[i].br / A.tkByPrio[i].n) * 100 : 0,
  }));
  const crit = prioBad.find((x) => x.p.n === "Critical") || prioBad[0];
  const low = prioBad.find((x) => x.p.n === "Low") || prioBad[prioBad.length - 1];

  document.getElementById("qaBlock").innerHTML = `
    <div class="qa"><div class="q">1. Which merchants generate the highest sales value and transaction volume?</div>
      <p><strong>${top[0].m.n}</strong> leads on both, at ${zar(top[0].v)} and
      ${num(A.txByMerch[M.indexOf(top[0].m)])} transactions. The top five merchants
      take ${pct(con.top5_share)} of all sales and the top ten ${pct(con.top10_share)};
      it takes ${con.merchants_to_80pct} of the ${M.length} merchants to reach 80% of revenue.
      Concentration is moderate rather than dangerous, but the top three are large
      enough that any one of them stalling is visible at group level.</p></div>

    <div class="qa"><div class="q">2. Which voucher type has the highest redemption rate?</div>
      <p><strong>${bestVt[0].v}</strong> at ${pct(bestVt[0].rate)}, against
      ${bestVt[bestVt.length - 1].v} at ${pct(bestVt[bestVt.length - 1].rate)} - a spread of
      ${(bestVt[0].rate - bestVt[bestVt.length - 1].rate).toFixed(1)} points. The split
      tracks the settlement model rather than anything merchant-specific: prepaid
      types redeem fastest, third-party settled types lag.</p></div>

    <div class="qa"><div class="q">3. Which region shows declining sales or transaction behaviour?</div>
      <p><strong>${worstRegion.r}</strong> is the only region with negative momentum,
      at ${signed(worstRegion.mom)} for the latest month against its prior three-month
      average. That is a composition effect rather than a regional collapse: it is
      driven by individual merchants inside the region, not by every merchant there
      softening together.</p></div>

    <div class="qa"><div class="q">4. Are ticket volumes, priority or long resolution times associated with weaker merchant performance?</div>
      <p>Yes, but only for volume, and the effect is concentrated rather than general.
      Ticket intensity correlates with month-on-month growth at
      <strong>r = ${c.tickets_per_1k_tx_vs_mom}</strong> across merchants. At
      merchant-month grain, months following a ticket surge of ten or more averaged
      <strong>${signed(c.mom_when_ticket_surge)}</strong> sales growth against
      <strong>${signed(c.mom_when_no_surge)}</strong> in all other months -
      but on only ${c.surge_month_count} surge months, so treat it as a strong
      signal on thin evidence rather than an established elasticity.
      Average resolution hours show no such relationship
      (r = ${c.avg_resolution_hours_vs_mom}), and neither does breach rate
      (r = ${c.sla_breach_pct_vs_mom}). <strong>Ticket volume is the leading
      indicator; resolution speed is not.</strong></p></div>

    <div class="qa"><div class="q">5. Which merchants should management focus on first, and why?</div>
      <p>${declining.length ? declining.map((o) =>
        `<strong>${o.m.n}</strong> (${signed(o.m.mom)} month on month)`).join(", ")
        : "No merchant is declining more than 10% month on month"}.
      ${declining.length ? `The decline arrived in the same month as a support-ticket
      spike, which makes it an operational problem to fix rather than a market loss
      to accept.` : ""} Below that, the health score puts
      ${M.filter((m) => m.tier === "Critical" || m.tier === "At risk").length}
      merchants in the bottom two risk tiers.</p></div>`;

  document.getElementById("recBlock").innerHTML = `
    <ul>
      <li><strong>Re-triage the support queue this week.</strong> Critical tickets
        average <strong>${crit.res.toFixed(1)} hours</strong> against a
        ${crit.p.sla}-hour target and breach ${pct(crit.br, 0)} of the time, while Low
        tickets close in ${low.res.toFixed(1)} hours against a ${low.p.sla}-hour target
        and breach ${pct(low.br, 0)}. The queue is being worked in the wrong order - the
        highest-priority work is the slowest served. This is the single cheapest fix
        on the list and it needs no new data.</li>
      ${declining.length ? `<li><strong>Put ${declining[0].m.n} on a recovery plan.</strong>
        Sales ${signed(declining[0].m.mom)} month on month with a simultaneous ticket
        spike. Confirm whether the tickets caused the decline or merely accompanied it,
        then clear the backlog before the next billing cycle.</li>` : ""}
      <li><strong>Investigate the redemption-lag incident before closing it.</strong>
        One region and voucher-type combination ran at roughly four times its normal
        redemption lag for a month. A model trained on the months before it could not
        predict it (AUC ${ml.delayAuc.toFixed(2)}), which says it was an isolated
        operational event, not a standing pattern - so the fix is a root-cause review,
        not a forecasting model.</li>
      <li><strong>Book the non-redemption exposure.</strong> The redemption model puts
        roughly <strong>${compact(ml.breakage)}</strong> of voucher value at low
        probability of ever being redeemed. Finance should treat that as a breakage
        estimate with a stated confidence rather than as certain revenue.</li>
      <li><strong>Protect the growth account.</strong> One merchant stepped up to a new
        sales level and has held it for three months. Understand what changed there
        before assuming it repeats, and check the same lever applies to the
        long tail.</li>
      <li><strong>Add a population reference feed before acting on the map.</strong>
        The network serves ${new Set(M.map((m) => m.r)).size} of
        ${DATA.geo.provinces.length} provinces, and the unserved ones cover
        ${pct(DATA.geo.provinces.filter((p) => !p.covered)
             .reduce((a, p) => a + p.areaSqKm, 0)
           / DATA.geo.provinces.reduce((a, p) => a + p.areaSqKm, 0) * 100, 0)}
        of South Africa's land area. That is a footprint observation, not a market
        opportunity - land area is not demand, and the largest unserved province is
        also among the least populated. Coverage cannot be judged properly until a
        population or outlet-count feed is added.</li>
    </ul>`;

  document.getElementById("assumeBlock").innerHTML = `
    <h3>Assumptions</h3>
    <ul>
      <li>A voucher redeemed more than <strong>7 days</strong> after sale counts as
        delayed. The observed median lag is about 3 days for every voucher type, so
        7 days sits well outside normal behaviour. The threshold is a parameter in
        the Silver notebook, not a hard-coded constant.</li>
      <li>Unredeemed vouchers are excluded from the delay rate rather than counted as
        on-time. They have no outcome yet; averaging them in as zeros would
        understate the delay rate.</li>
      <li>Merchant name, region and channel are taken from the reference file only.
        They also appear on all three fact files and were verified to agree on every
        row, so the duplicates were dropped rather than reconciled.</li>
      <li><code>SLAHours</code> is a fixed property of the priority tier, verified
        one-to-one, so it lives on the priority dimension.</li>
      <li>Target attainment uses <code>BaseMonthlySalesTarget</code> multiplied by the
        number of months in the period. No phasing or seasonality is applied to the
        target because none was supplied.</li>
    </ul>
    <h3>Data quality</h3>
    <ul>
      <li>All 20 referential-integrity, grain and null checks pass. No orphan keys,
        no duplicate business keys, no negative values, no redemption dated before
        its sale.</li>
      <li>${num(DATA.tick.d.length)} tickets carry a resolution-hours value regardless
        of status, so for still-open tickets that figure is elapsed time, not time to
        resolution. Average resolution therefore mixes two definitions - the source
        data dictionary states this, and it is not separable from what was supplied.</li>
      <li>Support tickets have no voucher type, so the voucher-type slicer cannot
        filter them. It is left un-applied to ticket visuals rather than silently
        dropping rows.</li>
    </ul>
    <h3>Limitations</h3>
    <ul>
      <li>Seven months of history, one year only. No year-on-year comparison is
        possible and no annual seasonality can be separated from trend.</li>
      <li>25 merchants is too few to train and validate a churn classifier honestly.
        The health score is therefore a transparent weighted percentile index, not a
        fitted model - every component is visible and re-weightable.</li>
      <li>Because the health score is percentile-based, a quarter of merchants always
        land in the bottom tier. It ranks relative risk within the book; it does not
        say the book is unhealthy.</li>
      <li>The delayed-redemption model scores near chance
        (AUC ${ml.delayAuc.toFixed(2)}). That is a finding, not a failure: the delay
        was a one-off incident with no predictive signature in the preceding months.</li>
      <li>The forecast beats a seasonal-naive benchmark by
        ${(ml.naiveMape - ml.mape).toFixed(2)} percentage points of MAPE. That is a
        real but slim margin on 28 held-out days; it should be re-backtested as
        history accumulates.</li>
    </ul>`;
}

/* ------------------------------------------------------------------ wiring */
function chipRow(host, values, set, onChange) {
  const h = document.getElementById(host);
  h.innerHTML = "";
  values.forEach((v) => {
    const b = el2("button");
    b.className = "chip"; b.type = "button"; b.textContent = v;
    b.setAttribute("aria-pressed", set.has(v));
    b.addEventListener("click", () => {
      // Clicking the only active value re-selects everything, so a filter can
      // never leave the report empty with no obvious way back.
      if (set.has(v) && set.size === 1) values.forEach((x) => set.add(x));
      else if (set.has(v)) set.delete(v);
      else set.add(v);
      onChange();
    });
    h.appendChild(b);
  });
}

function renderFilters() {
  chipRow("fRegion", REGIONS, state.regions, refresh);
  chipRow("fVoucher", DATA.vt, state.vtypes, refresh);
  chipRow("fChannel", CHANNELS, state.channels, refresh);
  const from = document.getElementById("fFrom"), to = document.getElementById("fTo");
  if (!from.options.length) {
    MONTHS.forEach((m, i) => {
      from.appendChild(new Option(m, i)); to.appendChild(new Option(m, i));
    });
    from.addEventListener("change", () => {
      state.from = +from.value;
      if (state.to < state.from) { state.to = state.from; to.value = state.to; }
      refresh();
    });
    to.addEventListener("change", () => {
      state.to = +to.value;
      if (state.from > state.to) { state.from = state.to; from.value = state.from; }
      refresh();
    });
  }
  from.value = state.from; to.value = state.to;
  const nMerch = M.filter((m, i) => state.regions.has(m.r) && state.channels.has(m.c)).length;
  document.getElementById("filterSummary").textContent =
    `${nMerch} of ${M.length} merchants · ${state.to - state.from + 1} of ${NMONTH} months`
    + (state.vtypes.size < DATA.vt.length ? " · voucher filter does not apply to tickets" : "");
}

function refresh() {
  A = aggregate();
  renderFilters();
  ({ exec: renderExec, merchant: renderMerchant, ops: renderOps, geo: renderGeo,
     ai: renderAI, notes: renderNotes }[state.page])();
}

function showPage(p) {
  state.page = p;
  document.querySelectorAll("nav.tabs button").forEach((b) =>
    b.setAttribute("aria-selected", b.dataset.page === p));
  document.querySelectorAll(".page").forEach((s) =>
    (s.hidden = s.id !== "page-" + p));
  refresh();
}

document.querySelectorAll("nav.tabs button").forEach((b) =>
  b.addEventListener("click", () => showPage(b.dataset.page)));
document.getElementById("fReset").addEventListener("click", () => {
  REGIONS.forEach((r) => state.regions.add(r));
  DATA.vt.forEach((v) => state.vtypes.add(v));
  CHANNELS.forEach((c) => state.channels.add(c));
  state.from = 0; state.to = NMONTH - 1;
  refresh();
});
document.getElementById("drillClose").addEventListener("click", closeDrill);
document.getElementById("backdrop").addEventListener("click", closeDrill);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrill(); });
document.querySelectorAll("[data-toggle]").forEach((b) =>
  b.addEventListener("click", () => {
    const t = document.getElementById(b.dataset.toggle);
    t.hidden = !t.hidden;
    b.textContent = t.hidden ? "Show as table" : "Hide table";
  }));

const themeBtn = document.getElementById("themeToggle");
themeBtn.addEventListener("click", () => {
  const dark = document.documentElement.getAttribute("data-theme") === "dark"
    || (!document.documentElement.getAttribute("data-theme")
        && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
  themeBtn.textContent = dark ? "Dark mode" : "Light mode";
  refresh();
});

let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(refresh, 140);
});

document.getElementById("periodLabel").textContent =
  `${DATA.meta.periodStart} to ${DATA.meta.periodEnd} · ${M.length} merchants · built ${DATA.meta.generated}`;
showPage("exec");
