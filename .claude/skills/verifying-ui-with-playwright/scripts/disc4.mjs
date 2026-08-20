import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
await p.getByText(/Configure strategies/).click();
await p.waitForTimeout(7000);
const r = await p.evaluate(() => {
  const btns = [...document.querySelectorAll('button')].filter(b=>/1 YEAR/i.test(b.innerText));
  return {
    total: btns.length,
    visible: btns.filter(b=>b.offsetParent!==null).length,
    // which container each lives in — the grid, or somewhere else entirely
    where: btns.map(b => {
      const c = b.closest('[data-testid="stExpander"]') ? 'expander' : 'page';
      return c + (b.offsetParent===null ? ':hidden' : ':shown');
    }),
    checkVisible: [...document.querySelectorAll('[data-testid="stCheckbox"]')]
                    .filter(e=>e.offsetParent!==null).length,
  };
});
console.log(JSON.stringify(r,null,1));
await b.close();
