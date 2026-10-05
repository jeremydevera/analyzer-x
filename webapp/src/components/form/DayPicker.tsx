"use client";

import { useEffect, useRef } from "react";
import flatpickr from "flatpickr";
import "flatpickr/dist/flatpickr.css";

/** A day box whose calendar opens ABOVE the box (operator, Oct 05, 2026:
 *  "when i click the calendar, the pop is showing under, its very hard to
 *  click, it should be above"). The browser's own date input decides where
 *  its calendar goes and cannot be told; flatpickr can (`position`).
 *
 *  `value` / `min` / `max` / `onChange` are the day keys a date input uses
 *  ("2026-10-01"), so it swaps in for `<input type="date">` with no other
 *  change; the box itself reads "Oct 01, 2026". On a phone flatpickr hands
 *  over to the phone's own picker, which opens as a full-screen sheet. */
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
      dateFormat: "Y-m-d",
      altInput: true,
      altFormat: "M d, Y",
      altInputClass: className,
      position: "above",
      monthSelectorType: "static",
      defaultDate: value || undefined,
      onChange: (_sel, day) => { if (day) changed.current(day); },
    });
    fp.current = Array.isArray(inst) ? inst[0] : inst;
    fp.current?.altInput?.setAttribute("aria-label", label);
    return () => { fp.current?.destroy(); fp.current = null; };
    // created once; value and the limits are pushed in below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const f = fp.current;
    if (!f) return;
    f.set("minDate", min || undefined);
    f.set("maxDate", max || undefined);
    if (value && f.input.value !== value) f.setDate(value, false);
  }, [value, min, max]);

  return <input ref={box} type="text" aria-label={label} className={className} defaultValue={value} />;
}
