/* The UI gate. `node gate.mjs [?p=slug] [selector-to-crop]`
   Runs the five checks the skill describes and exits non-zero on failure, so a
   UI change cannot be reported done while any of them is red. */
import { chromium } from 'playwright';

const PAGE = process.argv[2] || '';
const CROP = process.argv[3] || null;
const URL = 'http://localhost:8503/' + (PAGE.startsWith('?') ? PAGE : '');

const b = await chromium.launch();
const p = await b.newPage();
const errs = [];
p.on('pageerror', e => errs.push(String(e).slice(0, 120)));
await p.setViewportSize({ width: 1600, height: 1050 });
await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
await p.waitForFunction(() => document.querySelector('h1') !== null, { timeout: 120000 });
await p.waitForTimeout(4000);

const out = await p.evaluate(() => {
  const fail = [], note = [];

  // colours resolved BY THE BROWSER — never parsed by hand
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const srgb = c => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000';
    cx.fillStyle = c; cx.fillRect(0,0,1,1);
    const d = cx.getImageData(0,0,1,1).data; return [d[0],d[1],d[2],d[3]/255]; };
  const lum = c => { const [r,g,bl] = srgb(c).map(x=>x/255)
      .map(x => x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4));
    return 0.2126*r + 0.7152*g + 0.0722*bl; };
  // COMPOSITE, do not stop at the first tinted ancestor. Streamlit lays a
  // rgba(180,172,156,0.15) highlight over rows; treating a 15%-alpha tint as an
  // opaque ground reported white-on-dark as 2.16:1 and sent me hunting a UI bug
  // that did not exist. Layers are collected upward then flattened downward.
  const bgOf = el => {
    const layers = [];
    let n = el;
    while (n) {
      const c = getComputedStyle(n).backgroundColor;
      if (c) { const v = srgb(c); if (v[3] > 0.001) { layers.push(v);
        if (v[3] >= 0.999) break; } }
      n = n.parentElement;
    }
    let [r, g, b] = layers.length && layers[layers.length-1][3] >= 0.999
      ? layers.pop() : [0, 0, 0];
    for (let i = layers.length - 1; i >= 0; i--) {
      const [sr, sg, sb, sa] = layers[i];
      r = sr*sa + r*(1-sa); g = sg*sa + g*(1-sa); b = sb*sa + b*(1-sa);
    }
    return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
  };
  const tok = name => { const s = document.createElement('span');
    document.body.appendChild(s); s.style.color = `var(${name})`;
    const v = getComputedStyle(s).color; s.remove(); return v; };

  // 1. NESTED CHROME — a composite control's inner input owns no chrome
  let composites = 0;
  for (const w of document.querySelectorAll('[data-baseweb="select"]')) {
    const inp = w.querySelector('input'); if (!inp) continue;
    composites++;
    const cs = getComputedStyle(inp);
    if (cs.borderTopWidth !== '0px')
      fail.push(`inner select input has a ${cs.borderTopWidth} border`);
    if (!['0px','auto'].includes(cs.minHeight))
      fail.push(`inner select input has min-height ${cs.minHeight}`);
    if (parseFloat(cs.borderTopLeftRadius) > 0)
      fail.push(`inner select input has radius ${cs.borderTopLeftRadius}`);
  }
  if (!composites) note.push('no composite selects on this page — check skipped');

  // 2. CONTRAST, with the correct floor per text size
  let checked = 0;
  const seen = new Set();
  for (const el of document.querySelectorAll('p,span,label,div,button,a,b,i,h1,h2,h3,td,th')) {
    if (el.children.length || el.offsetParent === null) continue;
    if (el.classList.contains('ani-sr')) continue;      // 1x1 accessible copy
    const t = el.innerText?.trim();
    if (!t || t.length > 40 || seen.has(t)) continue;
    seen.add(t); checked++;
    const cs = getComputedStyle(el);
    const a = lum(cs.color), z = lum(bgOf(el));
    const ratio = (Math.max(a,z)+0.05)/(Math.min(a,z)+0.05);
    const px = parseFloat(cs.fontSize);
    const large = px >= 24 || (px >= 18.66 && (parseInt(cs.fontWeight)||400) >= 700);
    const floor = large ? 3.0 : 4.5;
    if (ratio < floor) fail.push(`contrast ${ratio.toFixed(2)} < ${floor} on "${t.slice(0,26)}"`);
  }
  if (!checked) fail.push('contrast check found NO text — the probe is broken');

  // 3. MID-WORD BREAKS — real line boxes, not an element-height heuristic
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walk.nextNode())) {
    const t = n.nodeValue?.trim();
    if (!t || /\s/.test(t) || t.length > 24) continue;
    const el = n.parentElement;
    if (!el || el.offsetParent === null || el.classList.contains('ani-sr')) continue;
    // st.dataframe ships an INVISIBLE accessibility mirror of its grid
    // (td[data-testid^="glide-cell"]) with zero-width cells. A long symbol
    // "breaks" in there and is never on screen — flagging it is the same class
    // of false positive as measuring the 1x1 .ani-sr copy.
    const box = el.getBoundingClientRect();
    if (box.width < 2 || box.height < 2) continue;
    if ((el.getAttribute('data-testid') || '').startsWith('glide-cell')) continue;
    if (el.closest('[data-testid="stDataFrameResizable"],.glideDataEditor')) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    if (r.getClientRects().length > 1) {
      // Name the offender. A failure that does not say WHICH element it is
      // costs a diagnostic round trip every time.
      const id = el.tagName.toLowerCase()
        + (el.getAttribute('data-testid') ? `[${el.getAttribute('data-testid')}]` : '')
        + (el.className ? '.' + String(el.className).split(' ')[0].slice(0,22) : '');
      fail.push(`"${t}" breaks mid-word in ${id} (${Math.round(box.width)}px)`);
    }
  }

  // 4. SEMANTIC COLOUR — money hues need a non-colour cue
  const pos = tok('--pos'), neg = tok('--neg');
  if (pos && neg && pos !== neg) {
    for (const el of document.querySelectorAll('span,b,div,td,i')) {
      if (el.offsetParent === null) continue;
      const t = (el.innerText||'').trim();
      if (!t || t.length > 30 || /\n/.test(t)) continue;
      const c = getComputedStyle(el).color;
      if (c !== pos && c !== neg) continue;
      const unit = el.closest('.mv-barrier,.mv-cell,.mv-row,.tm-h,.nvx-i,[data-testid="stColumn"]') || el;
      const ut = (unit.innerText||'').trim();
      const cue = /^[+-]/.test(t) || /[▲▼↑↓]/.test(t) || /[A-Za-z]/.test(t)
                || /[A-Za-z]/.test(ut) || /[▲▼↑↓]/.test(ut);
      if (!cue) fail.push(`"${t}" carries meaning in colour alone`);
    }
  } else note.push('--pos/--neg unresolved — semantic check skipped');

  // 5. DUPLICATION + layout
  const titles = [...document.querySelectorAll('h2')]
    .filter(h => h.offsetParent).map(h => h.innerText.replace(/\s+/g,' ').trim());
  const dupes = titles.filter((t,i) => titles.indexOf(t) !== i);
  if (dupes.length) fail.push(`duplicate sections: ${[...new Set(dupes)].join(', ')}`);

  const main = document.querySelector('.stMain') || document.body;
  if (main.scrollWidth > main.clientWidth + 1) fail.push('page scrolls sideways');

  // heading outline must not skip a level
  const lv = [...document.querySelectorAll('h1,h2,h3,h4')]
    .filter(h => h.offsetParent).map(h => +h.tagName[1]);
  for (let i = 1; i < lv.length; i++)
    if (lv[i] - lv[i-1] > 1) fail.push(`heading jumps h${lv[i-1]}->h${lv[i]}`);

  return {fail, note, stats:{textChecked:checked, composites, headings:lv.length}};
});

// ---- CHECK 6: OPEN STATE. A menu, popover or tooltip only exists while it is
// open, and baseweb renders it in a PORTAL at body level — outside .stApp. Every
// check above therefore ran on a page where the dropdowns were shut, and passed
// while an open menu was paper-white behind white text at 1.03:1. Nothing that
// only appears on interaction can be verified without performing it.
const overlay = [];
let openedOk = 0;
const triggers = await p.$$('[data-baseweb="select"]');
const nSel = Math.min(triggers.length, 3);
for (let i = 0; i < nSel; i++) {
  try {
    // RE-QUERY every pass. Streamlit reruns on interaction, which detaches the
    // handles collected before the loop — reusing them made every click fail
    // and the check reported "verified NOTHING" while the menu was fine.
    const live = p.locator('[data-baseweb="select"]').nth(i);
    await live.scrollIntoViewIfNeeded({timeout: 4000});
    // Try "Select all" first so at least one pass sees the EMPTY state, which
    // is a different element from the populated list and was broken while the
    // populated one measured clean.
    if (i === 0) {
      await live.click({timeout: 5000}).catch(()=>{});
      await p.waitForTimeout(500);
      const sa = p.locator('li', {hasText: /^Select all$/}).first();
      if (await sa.count()) { await sa.click({timeout: 3000}).catch(()=>{});
                              await p.waitForTimeout(1200); }
      await p.keyboard.press('Escape').catch(()=>{});
      await p.waitForTimeout(400);
    }
    await live.click({timeout: 5000});
    await p.waitForSelector('[data-baseweb="popover"],[data-baseweb="menu"]',
                            {timeout: 5000});
    // NO settle wait here. A click makes Streamlit rerun, and the rerun closes
    // the portal — a 500ms pause meant the overlay was already gone by the time
    // the checks ran, and the gate reported it had verified nothing.
    const bad = await p.evaluate(() => {
      const pop = document.querySelector('[data-baseweb="popover"],[data-baseweb="menu"]');
      if (!pop) return ['__none__'];
      const cv = document.createElement('canvas'); cv.width = cv.height = 1;
      const cx = cv.getContext('2d', {willReadFrequently: true});
      const srgb = c => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000';
        cx.fillStyle = c; cx.fillRect(0,0,1,1);
        const d = cx.getImageData(0,0,1,1).data; return [d[0],d[1],d[2],d[3]/255]; };
      const lum = c => { const [r,g,bl] = srgb(c).map(x=>x/255)
        .map(x => x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4));
        return 0.2126*r + 0.7152*g + 0.0722*bl; };
      const bgOf = el => {          // same compositing as the page check
        const layers = []; let n = el;
        while (n) { const c = getComputedStyle(n).backgroundColor;
          if (c) { const v = srgb(c); if (v[3] > 0.001) { layers.push(v);
            if (v[3] >= 0.999) break; } }
          n = n.parentElement; }
        let [r,g,b] = layers.length && layers[layers.length-1][3] >= 0.999
          ? layers.pop() : [0,0,0];
        for (let i = layers.length-1; i >= 0; i--) {
          const [sr,sg,sb,sa] = layers[i];
          r = sr*sa + r*(1-sa); g = sg*sa + g*(1-sa); b = sb*sa + b*(1-sa); }
        return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`; };
      const out = [];
      // EVERY element in the overlay, not just the text. The empty state
      // ("No results") is its own element with its own fill —
      // stSelectboxVirtualDropdownEmpty, a different testid from the populated
      // list — so checking only text contrast passed a paper-white panel.
      const appL = lum(bgOf(document.querySelector('.stApp')));
      const dark = appL < 0.35;
      const walkFills = (el, d) => {
        const v = srgb(getComputedStyle(el).backgroundColor);
        if (v[3] > 0.05) {
          const l = lum(`rgb(${v[0]},${v[1]},${v[2]})`);
          if (dark ? l > 0.55 : l < 0.12)
            out.push(`overlay fill ${dark ? 'LIGHT on a dark app' : 'DARK on a light app'}`
                     + `: ${el.tagName.toLowerCase()}`
                     + `[${el.getAttribute('data-testid') || el.getAttribute('data-baseweb') || '?'}]`);
        }
        for (const k of el.children) if (d < 8) walkFills(k, d + 1);
      };
      walkFills(pop, 0);
      // the overlay must not be wearing a light theme on a dark app (or vice versa)
      const appBg = lum(bgOf(document.querySelector('.stApp')));
      const popBg = lum(bgOf(pop));
      if (Math.abs(appBg - popBg) > 0.25)
        out.push(`overlay ground ${popBg.toFixed(3)} vs app ${appBg.toFixed(3)} — wrong theme`);
      for (const el of pop.querySelectorAll('li,div,span')) {
        if (el.children.length || el.offsetParent === null) continue;
        const t = el.innerText?.trim(); if (!t || t.length > 40) continue;
        const cs = getComputedStyle(el);
        const a = lum(cs.color), z = lum(bgOf(el));
        const ratio = (Math.max(a,z)+0.05)/(Math.min(a,z)+0.05);
        if (ratio < 4.5) out.push(`open menu: "${t.slice(0,22)}" at ${ratio.toFixed(2)}`);
      }
      return [...new Set(out)].slice(0, 4);
    });
    if (bad.includes('__none__')) {
      console.log(`note       dropdown ${i}: portal gone by evaluate time`);
    } else {
      openedOk++;                       // this one really was inspected
      overlay.push(...bad);
    }
    await p.keyboard.press('Escape');
    await p.waitForTimeout(250);
  } catch (e) { overlay.push('__none__');
    console.log(`note       dropdown ${i} did not open: `
                + String(e.message || e).split('\n')[0].slice(0, 90)); }
}
const opened = overlay.filter(x => x !== '__none__');
// Count what was actually INSPECTED. Inferring it from the failure array was
// wrong twice: [].every() is true for a clean run, and one un-openable control
// among several then failed the whole page.
const noneOpened = triggers.length > 0 && openedOk === 0;
if (!triggers.length)
  console.log('note       no dropdowns on this page — open-state check skipped');
else if (noneOpened)
  out.fail.push('no dropdown would open — the open-state check verified NOTHING');
else
  console.log(`note       inspected ${openedOk} of ${triggers.length} dropdown(s), `
              + `${opened.length ? opened.length + ' problem(s)' : 'overlay clean'}`);
if (opened.length) out.fail.push(...new Set(opened));

if (CROP) {
  const el = await p.$(CROP);
  if (el) { await el.scrollIntoViewIfNeeded(); await el.screenshot({path:'gate-crop.png'});
            console.log(`cropped ${CROP} -> gate-crop.png  (OPEN IT AND LOOK)`); }
  else console.log(`selector ${CROP} not found`);
}
await p.screenshot({path:'gate-full.png'});

console.log('stats     ', JSON.stringify(out.stats));
out.note.forEach(n => console.log('note      ', n));
if (errs.length) out.fail.push(...errs.map(e => 'page error: ' + e));
if (out.fail.length) {
  console.log(`\nFAIL (${out.fail.length}):`);
  [...new Set(out.fail)].slice(0, 30).forEach(f => console.log('  -', f));
} else {
  console.log('\nall six checks PASS — now OPEN gate-full.png and read it');
}
await b.close();
process.exit(out.fail.length ? 1 : 0);
