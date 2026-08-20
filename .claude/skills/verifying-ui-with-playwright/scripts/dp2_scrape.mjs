import { chromium } from "playwright";
import fs from "fs";

const DIR = "/Users/jeremydevera/Desktop/Trading Agents/.claude/skills/verifying-ui-with-playwright/scripts";
const BASE = "https://zenith-shadcn.dashboardpack.com";
const PAGES = ["/forms", "/customers", "/charts", "/billing", "/settings"];

const EXTRACT = () => {
  const PROPS = ["backgroundColor","color","borderColor","borderWidth","borderStyle","borderRadius","boxShadow","padding","fontSize","fontWeight","fontFamily","letterSpacing","lineHeight","height","width","maxWidth","minWidth","display","flexGrow","gap","textTransform"];
  const st = (el) => {
    if (!el) return null;
    const c = getComputedStyle(el);
    const o = {};
    for (const p of PROPS) o[p] = c[p];
    const r = el.getBoundingClientRect();
    o._rectW = Math.round(r.width * 100) / 100;
    o._rectH = Math.round(r.height * 100) / 100;
    o._tag = el.tagName.toLowerCase();
    o._slot = el.getAttribute("data-slot") || null;
    o._cls = (el.className && typeof el.className === "string") ? el.className.slice(0, 200) : null;
    o._text = (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 60);
    return o;
  };
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const q = (sel) => [...document.querySelectorAll(sel)].filter(vis);
  const first = (sel) => q(sel)[0] || null;
  const MAIN = document.querySelector("main") || document.body;
  const inMain = (el) => MAIN.contains(el);
  const qm = (sel) => q(sel).filter(inMain);

  const out = {};

  /* ---------- CSS custom properties ---------- */
  const vars = {};
  const varSources = {};
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    if (!rules) continue;
    const walk = (rl, ctx) => {
      for (const r of rl) {
        if (r.cssRules && !r.selectorText) { walk(r.cssRules, (r.conditionText || r.media?.mediaText || ctx)); continue; }
        if (!r.style || !r.selectorText) continue;
        const sel = r.selectorText;
        if (!/(^|,)\s*(:root|html|\.dark|\[data-theme)/.test(sel)) continue;
        for (let i = 0; i < r.style.length; i++) {
          const n = r.style[i];
          if (!n.startsWith("--")) continue;
          const key = sel.includes(".dark") ? "dark:" + n : n;
          vars[key] = r.style.getPropertyValue(n).trim();
          varSources[key] = sel.slice(0, 80) + (ctx ? " @" + ctx : "");
        }
      }
    };
    walk(rules, null);
  }
  out.cssVarsDeclared = vars;
  out.cssVarNames = Object.keys(vars).sort();
  // resolved values on documentElement for every declared name
  const resolved = {};
  const rootCS = getComputedStyle(document.documentElement);
  const bodyCS = getComputedStyle(document.body);
  for (const k of new Set(Object.keys(vars).map(k => k.replace(/^dark:/, "")))) {
    const v = rootCS.getPropertyValue(k).trim();
    const bv = bodyCS.getPropertyValue(k).trim();
    resolved[k] = v || bv;
  }
  out.cssVarsResolvedDark = resolved;

  /* ---------- headings / typography samples ---------- */
  out.headings = q("h1,h2,h3,h4").filter(inMain).slice(0, 14).map(st);

  out.typography = {
    pageH1: st(qm("h1")[0] || qm("h2")[0]),
    cardTitle: st(first('[data-slot="card-title"]')),
    cardDescription: st(first('[data-slot="card-description"]')),
    label: st(qm('label,[data-slot="label"]')[0]),
    tableTh: st(first("thead th")),
    tableTd: st(first("tbody td")),
    inputText: st(qm('input[type=text],input:not([type=checkbox]):not([type=radio]):not([type=hidden])')[0]),
    buttonText: st(qm("button")[0]),
    body: (() => { const c = getComputedStyle(document.body); return { fontFamily: c.fontFamily, fontSize: c.fontSize, color: c.color, backgroundColor: c.backgroundColor }; })(),
    htmlBg: getComputedStyle(document.documentElement).backgroundColor,
  };

  /* ---------- inputs / fields + width rule ---------- */
  const labelFor = (el) => {
    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return l.textContent.trim(); }
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
      const l = p.querySelector("label");
      if (l && !l.contains(el)) return l.textContent.trim().slice(0, 40);
    }
    const al = el.getAttribute("aria-label"); if (al) return "[aria-label] " + al;
    const ph = el.getAttribute("placeholder"); if (ph) return "[placeholder] " + ph;
    return "(none)";
  };
  const gridAncestor = (el) => {
    let p = el.parentElement;
    for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
      const c = getComputedStyle(p);
      if (c.display === "grid") return { el: p, cols: c.gridTemplateColumns, gap: c.gap, rowGap: c.rowGap, colGap: c.columnGap, w: Math.round(p.getBoundingClientRect().width) };
    }
    return null;
  };
  const fieldRow = (el, kind) => {
    const s = st(el);
    const parent = el.parentElement;
    const pw = parent ? Math.round(parent.getBoundingClientRect().width * 100) / 100 : null;
    const gp = parent?.parentElement;
    const ga = gridAncestor(el);
    return {
      kind,
      label: labelFor(el),
      fieldWidthPx: s._rectW,
      containerWidthPx: pw,
      grandparentWidthPx: gp ? Math.round(gp.getBoundingClientRect().width * 100) / 100 : null,
      ratio: pw ? Math.round((s._rectW / pw) * 1000) / 1000 : null,
      computedWidth: s.width, maxWidth: s.maxWidth, minWidth: s.minWidth, flexGrow: s.flexGrow, display: s.display,
      grid: ga ? { cols: ga.cols, gap: ga.gap, rowGap: ga.rowGap, colGap: ga.colGap, containerW: ga.w } : null,
      style: s,
    };
  };

  const textInputs = qm('input[type=text],input[type=email],input[type=search],input[type=password],input[type=number],input[type=tel],input:not([type])').filter(e => e.type !== "checkbox" && e.type !== "radio" && e.type !== "hidden");
  out.textInputs = textInputs.map(e => fieldRow(e, "input"));
  out.combobox = qm('[role=combobox],button[aria-haspopup="listbox"],[data-slot="select-trigger"]').map(e => fieldRow(e, "combobox"));
  out.buttonHasPopup = qm('button[aria-haspopup]').slice(0, 10).map(e => ({ label: (e.textContent || "").trim().slice(0, 40), haspopup: e.getAttribute("aria-haspopup"), ...fieldRow(e, "haspopup-btn") }));
  out.textareas = qm("textarea").map(e => fieldRow(e, "textarea"));

  /* ---------- checkbox / radio / switch ---------- */
  out.checkbox = qm('[role=checkbox],button[role=checkbox],input[type=checkbox],[data-slot="checkbox"]').slice(0, 6).map(st);
  out.radio = qm('[role=radio],input[type=radio],[data-slot="radio-group-item"]').slice(0, 6).map(st);
  out.switches = q('[role=switch],[data-slot="switch"]').slice(0, 6).map(e => {
    const s = st(e);
    const thumb = e.querySelector("*");
    return { ...s, _state: e.getAttribute("data-state") || e.getAttribute("aria-checked"), thumb: thumb ? st(thumb) : null };
  });

  /* ---------- labels ---------- */
  out.labels = qm('label,[data-slot="label"]').slice(0, 8).map(e => {
    const s = st(e);
    // relation to its field
    let field = null;
    if (e.htmlFor) field = document.getElementById(e.htmlFor);
    if (!field) { const p = e.parentElement; field = p?.querySelector("input,textarea,[role=combobox],select"); }
    let rel = null;
    if (field) {
      const lr = e.getBoundingClientRect(), fr = field.getBoundingClientRect();
      rel = { labelTop: Math.round(lr.top), labelLeft: Math.round(lr.left), labelBottom: Math.round(lr.bottom),
              fieldTop: Math.round(fr.top), fieldLeft: Math.round(fr.left),
              position: (fr.top >= lr.bottom - 2) ? "above" : (Math.abs(fr.top - lr.top) < 12 ? "beside" : "other"),
              gapPx: Math.round(fr.top - lr.bottom) };
    }
    return { ...s, rel };
  });

  /* ---------- vertical gap between fields ---------- */
  const fieldsAll = [...textInputs, ...qm("textarea"), ...qm('[role=combobox],[data-slot="select-trigger"]')]
    .map(e => ({ e, r: e.getBoundingClientRect() })).sort((a, b) => a.r.top - b.r.top);
  out.fieldVerticalGaps = [];
  for (let i = 1; i < fieldsAll.length; i++) {
    const g = Math.round(fieldsAll[i].r.top - fieldsAll[i - 1].r.bottom);
    if (g >= 0 && g < 200) out.fieldVerticalGaps.push({ gap: g, prev: (fieldsAll[i-1].e.getAttribute("placeholder")||fieldsAll[i-1].e.id||fieldsAll[i-1].e.tagName), next: (fieldsAll[i].e.getAttribute("placeholder")||fieldsAll[i].e.id||fieldsAll[i].e.tagName) });
  }

  /* ---------- form grid layout ---------- */
  out.grids = [...MAIN.querySelectorAll("*")].filter(el => vis(el) && getComputedStyle(el).display === "grid").slice(0, 20).map(el => {
    const c = getComputedStyle(el);
    return { cols: c.gridTemplateColumns, gap: c.gap, rowGap: c.rowGap, colGap: c.columnGap, w: Math.round(el.getBoundingClientRect().width), children: el.children.length, cls: (typeof el.className === "string" ? el.className.slice(0, 120) : null) };
  });

  /* ---------- pills / badges ---------- */
  const pillCands = new Set([...qm('[data-slot="badge"]'), ...qm('[class*="badge"]')]);
  if (pillCands.size === 0) {
    for (const el of MAIN.querySelectorAll("span,div,p")) {
      if (!vis(el)) continue;
      const t = (el.textContent || "").trim();
      if (!t || t.length > 26) continue;
      if ([...el.children].some(c => c.tagName !== "SVG" && c.tagName !== "svg" && (c.textContent || "").trim())) continue;
      const c = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const hasBg = c.backgroundColor !== "rgba(0, 0, 0, 0)" && c.backgroundColor !== "transparent";
      const hasBorder = parseFloat(c.borderTopWidth) > 0;
      if (!(hasBg || hasBorder)) continue;
      if (parseFloat(c.borderTopLeftRadius) < 3) continue;
      if (r.width > 190 || r.height > 40 || r.height < 12) continue;
      if (parseFloat(c.fontSize) > 14) continue;
      pillCands.add(el);
    }
  }
  const seen = new Set();
  out.pills = [];
  for (const el of pillCands) {
    const s = st(el);
    const key = [s._text, s.backgroundColor, s.color, s.borderRadius, s.padding, s.fontSize, s.fontWeight].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.pills.push({ text: s._text, backgroundColor: s.backgroundColor, color: s.color, borderColor: s.borderColor, borderWidth: s.borderWidth, borderRadius: s.borderRadius, padding: s.padding, fontSize: s.fontSize, fontWeight: s.fontWeight, letterSpacing: s.letterSpacing, height: s._rectH, width: s._rectW, boxShadow: s.boxShadow, slot: s._slot, cls: s._cls });
    if (out.pills.length > 30) break;
  }

  /* ---------- tabs / segmented control ---------- */
  const tablists = q('[role=tablist],[data-slot="tabs-list"]');
  out.tabs = tablists.map(tl => ({
    container: st(tl),
    items: [...tl.querySelectorAll('[role=tab],[data-slot="tabs-trigger"],button')].filter(vis).map(t => ({
      state: t.getAttribute("data-state") || t.getAttribute("aria-selected"),
      ...st(t),
    })),
  }));
  // segmented-control fallback: groups of sibling buttons with a selected one
  out.segmentedFallback = [];
  if (tablists.length === 0) {
    for (const el of MAIN.querySelectorAll("div,nav")) {
      if (!vis(el)) continue;
      const btns = [...el.children].filter(c => c.tagName === "BUTTON" && vis(c));
      if (btns.length < 2 || btns.length > 6) continue;
      const c = getComputedStyle(el);
      if (parseFloat(c.borderTopLeftRadius) < 3 && c.backgroundColor === "rgba(0, 0, 0, 0)") continue;
      out.segmentedFallback.push({ container: st(el), items: btns.map(b => ({ state: b.getAttribute("data-state") || b.getAttribute("aria-current") || b.getAttribute("aria-pressed"), ...st(b) })) });
      if (out.segmentedFallback.length >= 3) break;
    }
  }

  /* ---------- buttons ---------- */
  out.buttons = qm("button").filter(b => (b.textContent || "").trim()).slice(0, 24).map(b => ({
    ...st(b),
    slot: b.getAttribute("data-slot"),
  }));

  /* ---------- table ---------- */
  const tbl = first("table");
  if (tbl) {
    let card = tbl.parentElement, cardEl = null;
    for (let i = 0; i < 6 && card; i++, card = card.parentElement) {
      const c = getComputedStyle(card);
      if ((c.backgroundColor !== "rgba(0, 0, 0, 0)" && c.backgroundColor !== "transparent") || parseFloat(c.borderTopWidth) > 0) { cardEl = card; break; }
    }
    out.table = {
      table: st(tbl),
      wrapperImmediate: st(tbl.parentElement),
      wrapperCard: st(cardEl),
      theadTr: st(tbl.querySelector("thead tr")),
      th: tbl.querySelectorAll("thead th").length ? [...tbl.querySelectorAll("thead th")].slice(0, 4).map(st) : null,
      tbodyTr: st(tbl.querySelector("tbody tr")),
      tbodyTr2: st(tbl.querySelectorAll("tbody tr")[1]),
      td: [...tbl.querySelectorAll("tbody tr:first-child td")].slice(0, 4).map(st),
      rowCount: tbl.querySelectorAll("tbody tr").length,
      colCount: tbl.querySelectorAll("thead th").length,
      borderCollapse: getComputedStyle(tbl).borderCollapse,
      thBorderBottom: (() => { const t = tbl.querySelector("thead th") || tbl.querySelector("thead tr"); if (!t) return null; const c = getComputedStyle(t); return { w: c.borderBottomWidth, c: c.borderBottomColor, s: c.borderBottomStyle }; })(),
      tdBorderBottom: (() => { const t = tbl.querySelector("tbody tr"); if (!t) return null; const c = getComputedStyle(t); return { w: c.borderBottomWidth, c: c.borderBottomColor, s: c.borderBottomStyle }; })(),
    };
  } else out.table = null;

  /* ---------- pagination ---------- */
  const pagTxt = /rows per page|per page|page \d+ of|previous|next|showing/i;
  let pagEl = null;
  for (const el of MAIN.querySelectorAll("div,nav,footer")) {
    if (!vis(el)) continue;
    const t = (el.innerText || "").trim();
    if (t.length > 160 || !pagTxt.test(t)) continue;
    if (el.querySelectorAll("button,a").length < 1) continue;
    pagEl = el;
  }
  out.pagination = pagEl ? {
    container: st(pagEl),
    text: (pagEl.innerText || "").replace(/\n+/g, " | ").slice(0, 160),
    controls: [...pagEl.querySelectorAll("button,a,[role=combobox]")].filter(vis).slice(0, 8).map(st),
  } : null;

  /* ---------- progress bars ---------- */
  out.progress = q('[role=progressbar],[data-slot="progress"]').slice(0, 8).map(e => {
    const s = st(e);
    const fill = e.querySelector("*");
    return { track: s, fill: fill ? st(fill) : null, aria: { now: e.getAttribute("aria-valuenow"), max: e.getAttribute("aria-valuemax") } };
  });
  out.progressHeuristic = [];
  if (out.progress.length === 0) {
    for (const el of MAIN.querySelectorAll("div")) {
      if (!vis(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.height > 14 || r.height < 3 || r.width < 40) continue;
      const c = getComputedStyle(el);
      if (c.backgroundColor === "rgba(0, 0, 0, 0)") continue;
      const kid = [...el.children].filter(vis)[0];
      out.progressHeuristic.push({ track: st(el), fill: kid ? st(kid) : null });
      if (out.progressHeuristic.length >= 6) break;
    }
  }

  /* ---------- cards ---------- */
  out.cards = qm('[data-slot="card"]').slice(0, 4).map(st);
  if (out.cards.length === 0) {
    out.cards = [...MAIN.querySelectorAll("div")].filter(el => {
      if (!vis(el)) return false;
      const c = getComputedStyle(el); const r = el.getBoundingClientRect();
      return parseFloat(c.borderTopLeftRadius) >= 6 && r.width > 200 && r.height > 80 &&
        (c.backgroundColor !== "rgba(0, 0, 0, 0)" || parseFloat(c.borderTopWidth) > 0);
    }).slice(0, 4).map(st);
  }

  /* ---------- data-slot inventory ---------- */
  const slots = {};
  for (const el of document.querySelectorAll("[data-slot]")) {
    const s = el.getAttribute("data-slot"); slots[s] = (slots[s] || 0) + 1;
  }
  out.dataSlotInventory = slots;

  out.viewport = { w: window.innerWidth, h: window.innerHeight };
  out.mainWidth = Math.round(MAIN.getBoundingClientRect().width);
  const sb = document.querySelector('[data-slot="sidebar"],aside,nav');
  out.sidebarWidth = sb ? Math.round(sb.getBoundingClientRect().width) : null;
  out.isDark = document.documentElement.classList.contains("dark");
  return out;
};

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, colorScheme: "dark" });
const pg = await ctx.newPage();
const RESULT = { base: BASE, theme: "dark", viewport: "1600x1000", scrapedAt: new Date().toISOString(), pages: {} };

for (const p of PAGES) {
  const name = p.replace("/", "");
  process.stderr.write(`--- ${p}\n`);
  await pg.goto(BASE + p, { waitUntil: "networkidle", timeout: 60000 });
  await pg.evaluate(() => { document.documentElement.classList.add("dark"); document.documentElement.style.colorScheme = "dark"; });
  await pg.waitForTimeout(1500);
  // settle any reveal animations
  await pg.evaluate(async () => { for (let y = 0; y < 4000; y += 500) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); } window.scrollTo(0, 0); });
  await pg.waitForTimeout(1200);

  const data = await pg.evaluate(EXTRACT);
  RESULT.pages[name] = data;

  await pg.screenshot({ path: `${DIR}/dp2_${name}.png` });

  // settings: walk the tabs to reach switches / radios / checkboxes
  if (p === "/settings") {
    RESULT.pages[name].tabPanels = {};
    const tabNames = await pg.$$eval('[role=tab]', els => els.map(e => e.textContent.trim()));
    for (const tn of tabNames) {
      try {
        await pg.click(`[role=tab]:has-text("${tn}")`, { timeout: 5000 });
        await pg.waitForTimeout(1200);
        const d = await pg.evaluate(EXTRACT);
        RESULT.pages[name].tabPanels[tn] = {
          switches: d.switches, checkbox: d.checkbox, radio: d.radio,
          textInputs: d.textInputs, textareas: d.textareas, combobox: d.combobox,
          labels: d.labels, grids: d.grids, pills: d.pills, buttons: d.buttons.slice(0, 10),
          fieldVerticalGaps: d.fieldVerticalGaps, dataSlotInventory: d.dataSlotInventory,
        };
        await pg.screenshot({ path: `${DIR}/dp2_settings_${tn.replace(/\W+/g, "")}.png` });
      } catch (e) { RESULT.pages[name].tabPanels[tn] = { error: String(e).slice(0, 120) }; }
    }
  }

  // hover a table row to capture :hover state
  if (await pg.locator("table tbody tr").count()) {
    const before = await pg.evaluate(() => { const t = document.querySelector("table tbody tr"); const c = getComputedStyle(t); return { backgroundColor: c.backgroundColor, color: c.color }; });
    await pg.locator("table tbody tr").first().hover();
    await pg.waitForTimeout(500);
    const after = await pg.evaluate(() => { const t = document.querySelector("table tbody tr"); const c = getComputedStyle(t); return { backgroundColor: c.backgroundColor, color: c.color }; });
    RESULT.pages[name].tbodyTrHover = { before, after, changed: JSON.stringify(before) !== JSON.stringify(after) };
  }

  // tooltip attempt
  try {
    const tt = pg.locator('[data-slot="tooltip-trigger"], [aria-describedby], button[title]').first();
    if (await tt.count()) {
      await tt.hover({ timeout: 4000 });
      await pg.waitForTimeout(1200);
      const t = await pg.evaluate(() => {
        const el = document.querySelector('[role=tooltip],[data-slot="tooltip-content"]');
        if (!el) return null;
        const c = getComputedStyle(el); const r = el.getBoundingClientRect();
        return { text: el.textContent.trim().slice(0, 60), backgroundColor: c.backgroundColor, color: c.color, borderRadius: c.borderRadius, padding: c.padding, fontSize: c.fontSize, fontWeight: c.fontWeight, boxShadow: c.boxShadow, borderWidth: c.borderWidth, borderColor: c.borderColor, w: Math.round(r.width), h: Math.round(r.height) };
      });
      RESULT.pages[name].tooltip = t;
    } else RESULT.pages[name].tooltip = null;
  } catch (e) { RESULT.pages[name].tooltip = null; }
}

fs.writeFileSync(`${DIR}/dp2_components.json`, JSON.stringify(RESULT, null, 1));
process.stderr.write("written\n");
await b.close();
