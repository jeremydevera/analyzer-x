"use client";

import { useEffect, useRef } from "react";
import flatpickr from "flatpickr";
import "flatpickr/dist/flatpickr.css";

const KEY = "Y-m-d";              // what a date input holds: "2026-10-01"
const SHOWN = "M d, Y";           // what the box shows: "Oct 01, 2026"

const asDate = (day?: string) => (day ? flatpickr.parseDate(day, KEY) ?? undefined : undefined);

/** Put the open calendar right ABOVE its box. flatpickr's "above" adds up
 *  the calendar's CHILDREN's heights, so this app's calendar styling
 *  (globals.css: p-5, mt-2, a border — 50px) left it sitting over its own box:
 *  bottom 875 against the box's top 827 (Chrome, Oct 05, 2026). */
function placeAbove(self: flatpickr.Instance) {
  requestAnimationFrame(() => {
    const cal = self.calendarContainer;
    const r = self._input.getBoundingClientRect();
    const margin = parseFloat(getComputedStyle(cal).marginTop) || 0;
    cal.style.top = `${r.top + window.scrollY - cal.offsetHeight - margin - 6}px`;
    cal.classList.remove("arrowTop");
    cal.classList.add("arrowBottom");
  });
}

/** A day box whose calendar opens ABOVE the box (operator, Oct 05, 2026:
 *  "when i click the calendar, the pop is showing under, its very hard to
 *  click, it should be above"). The browser's own date input decides where
 *  its calendar goes and cannot be told; flatpickr can (`position`).
 *
 *  `value` / `min` / `max` / `onChange` are the day keys a date input uses
 *  ("2026-10-01"), so it swaps in for `<input type="date">` with no other
 *  change; the box itself reads "Oct 01, 2026". ONE input: flatpickr's
 *  `altInput` adds a second box beside React's own, and in this app both
 *  stayed visible, with the calendar placed against the first (measured in
 *  Chrome, Oct 05, 2026). On a phone flatpickr hands over to the phone's own
 *  picker, which opens as a full-screen sheet. */
export default function DayPicker({ value, min, max, onChange, label, className = "" }: {
  value: string; min?: string; max?: string; onChange: (day: string) => void;
  label: string; className?: string;
}) {
  const box = useRef<HTMLInputElement>(null);
  const fp = useRef<flatpickr.Instance | null>(null);
  const changed = useRef(onChange);
  changed.current = onChange;

  useEffect(() => {
    if (!box.current) return;
    const inst = flatpickr(box.current, {
      dateFormat: SHOWN,
      position: "above",
      monthSelectorType: "static",
      defaultDate: asDate(value),
      minDate: asDate(min),
      maxDate: asDate(max),
      onChange: (sel) => { if (sel[0]) changed.current(flatpickr.formatDate(sel[0], KEY)); },
      onOpen: (_s, _d, self) => placeAbove(self),
    });
    fp.current = Array.isArray(inst) ? inst[0] : inst;
    return () => { fp.current?.destroy(); fp.current = null; };
    // created once; value and the limits are pushed in below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const f = fp.current;
    if (!f) return;
    f.set("minDate", asDate(min));
    f.set("maxDate", asDate(max));
    const cur = f.selectedDates[0] ? flatpickr.formatDate(f.selectedDates[0], KEY) : "";
    if (value && cur !== value) f.setDate(value, false, KEY);
  }, [value, min, max]);

  return <input ref={box} type="text" readOnly aria-label={label} className={className} />;
}
