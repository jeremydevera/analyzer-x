import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1000});
const URL='https://dashboardpack.com/live-demo-preview/?livedemo=391511';
await p.goto(URL, {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForTimeout(6000);
const info = await p.evaluate(() => ({
  title: document.title,
  iframes: [...document.querySelectorAll('iframe')].map(f=>({src:f.src, id:f.id,
            w:f.getBoundingClientRect().width, h:f.getBoundingClientRect().height})),
  links: [...document.querySelectorAll('a')].map(a=>a.href).filter(h=>/demo|preview|http/.test(h)).slice(0,15),
  bodyText: document.body.innerText.slice(0,400),
}));
console.log(JSON.stringify(info,null,1));
await p.screenshot({path:'dp_wrapper.png'});
await b.close();
