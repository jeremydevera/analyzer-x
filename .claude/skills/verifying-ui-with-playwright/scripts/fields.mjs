import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const probe = () => p.evaluate(() => {
  const out=[];
  const sel='input, textarea, [data-baseweb="select"], [data-testid="stSelectbox"],'
          + '[data-testid="stNumberInput"], [data-testid="stTextInput"],'
          + '[data-testid="stDateInput"], [data-testid="stMultiSelect"]';
  for (const el of document.querySelectorAll(sel)) {
    if (el.offsetParent===null) continue;
    const r=el.getBoundingClientRect(); if (r.width<2) continue;
    // what does the field actually need? longest option / current value
    const lab = el.getAttribute('aria-label') || el.closest('[data-testid="stElementContainer"]')
                  ?.querySelector('[data-testid="stWidgetLabel"]')?.innerText?.trim() || '';
    const val = (el.value ?? el.innerText ?? '').toString().trim().slice(0,20);
    out.push({lab:lab.slice(0,22), val, w:Math.round(r.width), tag:el.tagName,
              kind:el.getAttribute('data-testid')||el.getAttribute('data-baseweb')||''});
  }
  return out;
});
for (const nav of ['Auto Trade','Back Test','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav,{exact:true}).first().click();
  await p.waitForTimeout(6500);
  const f = await probe();
  const wide = f.filter(x=>x.w>240);
  console.log('==', nav, 'fields:', f.length, 'wider than 240px:', wide.length);
  for (const x of wide.slice(0,10)) console.log('   ', x.w+'px', JSON.stringify(x.lab), 'val='+JSON.stringify(x.val), x.kind);
}
await b.close();
