import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto("http://localhost:8503", { waitUntil: "networkidle" });
await p.waitForTimeout(9000);
const m = await p.evaluate(() => {
  const mk = (font) => { const s = document.createElement('span');
    s.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font:'+font;
    s.textContent = '0'.repeat(50); document.body.appendChild(s);
    const w = s.getBoundingClientRect().width/50; s.remove(); return +w.toFixed(2); };
  const txt = (font, t) => { const s = document.createElement('span');
    s.style.cssText='position:absolute;visibility:hidden;white-space:pre;font:'+font;
    s.textContent=t; document.body.appendChild(s);
    const w=s.getBoundingClientRect().width; s.remove(); return Math.round(w); };
  const mono13 = '13px "Fira Code", monospace';
  const sans13 = '13px "Fira Sans", sans-serif';
  const sans12 = '12px "Fira Sans", sans-serif';
  return {
    monoCh13: mk(mono13), sansCh13: mk(sans13), sansCh12: mk(sans12),
    samples: {
      "PROVE_USDT (mono13)": txt(mono13,"PROVE_USDT"),
      "trend50 (mono13)": txt(mono13,"trend50"),
      "Liquidity sweep 30 (sans13)": txt(sans13,"Liquidity sweep 30"),
      "TP 8.00% / SL 0.30% (mono13)": txt(mono13,"TP 8.00% / SL 0.30%"),
      "20x isolated (mono13)": txt(mono13,"20x isolated"),
      "-292.13 (mono13)": txt(mono13,"-292.13"),
      "1h (mono13)": txt(mono13,"1h"),
      "$5.00 (mono13)": txt(mono13,"$5.00"),
      "0.0004123 (mono13)": txt(mono13,"0.0004123"),
      "https://api.mexc.com/api/v3 (mono13)": txt(mono13,"https://api.mexc.com/api/v3"),
      "ANTHROPIC_API_KEY (mono13)": txt(mono13,"ANTHROPIC_API_KEY"),
      "claude-opus-4-1-20250805 (mono13)": txt(mono13,"claude-opus-4-1-20250805"),
      "ladder (sans12)": txt(sans12,"ladder"),
    }
  };
});
console.log(JSON.stringify(m, null, 1));
await b.close();
