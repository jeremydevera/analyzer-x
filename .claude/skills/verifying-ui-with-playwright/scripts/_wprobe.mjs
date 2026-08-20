import { chromium } from "playwright";
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1600,height:1000}});
await p.goto("http://localhost:8599",{waitUntil:"networkidle"}); await p.waitForTimeout(4000);
const out = await p.evaluate(()=>{
  const r=[];
  for (const t of ["stTextInput","stSelectbox","stNumberInput"]) {
    document.querySelectorAll(`[data-testid="${t}"]`).forEach((e,i)=>{
      const cs=getComputedStyle(e);
      r.push({t,i,w:Math.round(e.getBoundingClientRect().width),
              inlineW:e.style.width||"", cssMax:cs.maxWidth,
              parentW:Math.round(e.parentElement.getBoundingClientRect().width),
              parentInline:e.parentElement.style.width||"",
              parentTestid:e.parentElement.getAttribute("data-testid")});
    });
  }
  const hz=document.querySelectorAll('[data-testid="stHorizontalBlock"],[class*="stHorizontal"]');
  return {r, nHoriz:hz.length};
});
console.log(JSON.stringify(out,null,1));
await b.close();
