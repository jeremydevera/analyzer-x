import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a=0;a<4;a++){
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({force:true});
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
// measure the Close button against the row it belongs to
const m = await pg.evaluate(() => {
  const box = document.querySelector('.st-key-pos_real');
  const rows = [...box.querySelectorAll('.tm-pt:not(.tm-pt-h):not(.tm-pt-t)')];
  // VISIBLE buttons only: the confirm dialog keeps hidden ones in the DOM, and
  // measuring those produced a phantom -661px offset.
  const btns = [...box.querySelectorAll('button')].filter(b=>/close/i.test(b.innerText)
      && b.getBoundingClientRect().height > 0);
  const out = rows.slice(0, btns.length).map((r,i) => {
    const rb = r.getBoundingClientRect(), bb = btns[i].getBoundingClientRect();
    return { row: Math.round(rb.top+rb.height/2), btn: Math.round(bb.top+bb.height/2),
             offset: Math.round((bb.top+bb.height/2)-(rb.top+rb.height/2)),
             rowRight: Math.round(rb.right), btnLeft: Math.round(bb.left) };
  });
  const boxRect = box.getBoundingClientRect();
  const bd = getComputedStyle(box);
  // the TOTAL row: does any cell carry a stray dash?
  const tot = box.querySelector('.tm-pt-t');
  const cells = tot ? [...tot.children].map(c=>c.innerText.trim()) : [];
  // is anything drawing a border between the table and the buttons?
  const inner = [...box.querySelectorAll('[data-testid="stVerticalBlockBorderWrapper"]')]
    .map(e=>getComputedStyle(e).borderTopWidth);
  return { out, boxRight: Math.round(boxRect.right), boxBorder: bd.borderTopWidth+" "+bd.borderTopColor,
           totalCells: cells, innerBorders: inner };
});
console.log("Close button vs its row (offset 0 = centred):");
for (const r of m.out) console.log(`   row centre ${r.row}  button centre ${r.btn}  offset ${r.offset}px   row ends ${r.rowRight}, button starts ${r.btnLeft}`);
console.log("book box right edge:", m.boxRight, "| box border:", m.boxBorder);
console.log("inner wrapper borders:", JSON.stringify(m.innerBorders));
console.log("TOTAL row cells:", JSON.stringify(m.totalCells));
console.log("errors:", errs.length);
const box = pg.locator('.st-key-pos_real').first();
await box.scrollIntoViewIfNeeded(); await pg.waitForTimeout(700);
const bx = await box.boundingBox();
await pg.screenshot({ path: "pos-fixed.png", clip: { x: 150, y: Math.max(0,bx.y-60), width: 1640, height: 330 } });
await b.close();
