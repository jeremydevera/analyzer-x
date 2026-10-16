/** Where a day box's calendar opens, in window pixels (operator, Oct 05,
 *  2026: "it should be above"; Oct 16, 2026: a calendar opened above a box
 *  near the top of their window lost its month name, arrows and weekday row
 *  off the screen). Above when it fits, below when only that fits, and its
 *  top never outside the window. */
const EDGE = 8;   // keep clear of the window's edge
const GAP = 6;    // between the box and the calendar

export function placeCalendar(box: { top: number; bottom: number }, height: number,
                              viewHeight: number): { top: number; above: boolean } {
  const aboveTop = box.top - GAP - height;
  if (aboveTop >= EDGE) return { top: aboveTop, above: true };
  const belowTop = box.bottom + GAP;
  if (belowTop + height <= viewHeight - EDGE) return { top: belowTop, above: false };
  // fits neither side: the side with more room, slid back inside the window
  const roomAbove = box.top;
  const roomBelow = viewHeight - box.bottom;
  const above = roomAbove > roomBelow;
  const want = above ? aboveTop : belowTop;
  const top = Math.max(EDGE, Math.min(want, viewHeight - EDGE - height));
  return { top, above };
}
