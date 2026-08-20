import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1400 } });
await p.goto('http://localhost:8503/?p=auto-trade', { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(22000);
const out = await p.evaluate(() => {
  const q = s => [...document.querySelectorAll(s)];
  const depth = el => { let d = 0; while (el && el !== document.body) { d++; el = el.parentElement; } return d; };
  const sec = document.querySelector('.st-key-tmsec_strategy');
  const rows = sec ? q('.st-key-tmsec_strategy [data-testid="stHorizontalBlock"]') : [];
  const firstCell = sec ? sec.querySelector('[data-testid="stColumn"]') : null;
  // widget chain for one checkbox in the grid
  const cb = sec ? sec.querySelector('[data-testid="stCheckbox"]') : null;
  let chain = [];
  if (cb) { let e = cb; while (e && e !== document.body) { chain.push((e.tagName.toLowerCase()) + (e.getAttribute('data-testid') ? '[' + e.getAttribute('data-testid') + ']' : '') + (e.className && typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0,2).join('.') : '')); e = e.parentElement; } }
  return {
    totalNodes: document.querySelectorAll('*').length,
    horizontalBlocks: q('[data-testid="stHorizontalBlock"]').length,
    stColumns: q('[data-testid="stColumn"]').length,
    elementContainers: q('[data-testid="stElementContainer"]').length,
    verticalBlocks: q('[data-testid="stVerticalBlock"]').length,
    markdownContainers: q('[data-testid="stMarkdownContainer"]').length,
    buttons: q('.stButton button').length,
    checkboxes: q('[data-testid="stCheckbox"]').length,
    numberInputs: q('[data-testid="stNumberInput"]').length,
    expanders: q('[data-testid="stExpander"]').length,
    dataframes: q('[data-testid="stDataFrame"]').length,
    canvases: q('canvas').length,
    strategySection: sec ? {
      scrollWidth: sec.scrollWidth, clientWidth: sec.clientWidth,
      overflowX: getComputedStyle(sec).overflowX,
      horizontalBlocks: rows.length,
      columnsInside: q('.st-key-tmsec_strategy [data-testid="stColumn"]').length,
      firstColumnWidth: firstCell ? Math.round(firstCell.getBoundingClientRect().width) : null,
    } : null,
    checkboxAncestorChain: chain,
    checkboxWrapperDepth: cb ? depth(cb) : null,
    mvBlock: (() => { const m = document.querySelector('.mv'); return m ? { nodes: m.querySelectorAll('*').length, depthOfFirstCell: (() => { const c = m.querySelector('.mv-cell'); return c ? depth(c) : null; })() } : null; })(),
    sidebarWidth: (() => { const s = document.querySelector('[data-testid="stSidebar"]'); return s ? Math.round(s.getBoundingClientRect().width) : null; })(),
    navAnchors: q('a.nvx-i').length,
    navIsAnchor: q('[data-testid="stSidebar"] .stButton button').length,
  };
});
console.log(JSON.stringify(out, null, 1));
await b.close();
