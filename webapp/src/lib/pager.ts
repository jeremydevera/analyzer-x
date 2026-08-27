/** The page numbers a pager shows: 1, 2, a window around the current page, and
 *  the last two, with a null wherever a gap belongs.
 *
 *  The operator asked for "pagination like page 1 2 3 4" over a store of
 *  35,510,193 rows — 71,021 pages at 500 a page. Every app that pages billions
 *  of rows does it this way: numbers for the neighbourhood, an ellipsis for the
 *  distance, and a box to jump anywhere. Rendering 71,021 links is what those
 *  apps do NOT do.
 */
export function pageWindow(page: number, pages: number): (number | null)[] {
  const seen: number[] = [];
  const push = (n: number) => {
    if (n >= 1 && n <= pages && !seen.includes(n)) seen.push(n);
  };
  push(1);
  push(2);
  for (let n = page - 2; n <= page + 2; n++) push(n);
  push(pages - 1);
  push(pages);
  seen.sort((a, b) => a - b);
  const out: (number | null)[] = [];
  seen.forEach((n, i) => {
    if (i > 0 && n - seen[i - 1] > 1) out.push(null);
    out.push(n);
  });
  return out;
}
