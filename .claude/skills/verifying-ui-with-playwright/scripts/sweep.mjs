import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
for (const nav of ['Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav, {exact:true}).first().click();
  await p.waitForTimeout(7000);
  const r = await p.evaluate(() => ({
    h1: document.querySelector('h1')?.innerText,
    // how much of the screen is raw Streamlit widget chrome vs styled panels
    panels: document.querySelectorAll('.mv-card, .mv-panel, .tm-card').length,
    dataframes: document.querySelectorAll('[data-testid="stDataFrame"]').length,
    subheaders: [...document.querySelectorAll('h2,h3')].map(e=>e.innerText.trim()).slice(0,8),
    tabs: document.querySelectorAll('[data-testid="stTabs"] button').length,
  }));
  console.log(nav.padEnd(11), JSON.stringify(r));
  await p.screenshot({path:'sw_'+nav.replace(/ /g,'')+'.png'});
}
await b.close();
