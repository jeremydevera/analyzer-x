"use client";
/** A candlestick chart drawn on a canvas — no external library, because the
 * artifact CSP and this app both do better without a CDN. Wicks are drawn
 * from the real high/low, so a doji does not read as a gap. */
import { useEffect, useRef, useState } from "react";
import { Candle, cryptoApi } from "@/lib/api";

const INTERVALS: [string, string][] = [
  ["Min15", "15m"], ["Min60", "1h"], ["Hour4", "4h"], ["Day1", "1d"],
];

export default function CoinChart({ symbol }: { symbol: string }) {
  const [rows, setRows] = useState<Candle[]>([]);
  const [iv, setIv] = useState("Min60");
  const [err, setErr] = useState("");
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    cryptoApi.candles(symbol, iv, 180)
      .then((d) => { setRows(d.rows); setErr(""); })
      .catch((e) => { setRows([]); setErr(String(e)); });
  }, [symbol, iv]);

  useEffect(() => {
    const cv = ref.current;
    if (!cv || !rows.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d");
    if (!g) return;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, W, H);
    const hi = Math.max(...rows.map((r) => r.h));
    const lo = Math.min(...rows.map((r) => r.l));
    const pad = (hi - lo) * 0.08 || hi * 0.01;
    const top = hi + pad, bot = lo - pad;
    const y = (p: number) => H - ((p - bot) / (top - bot)) * H;
    const bw = Math.max(1.5, (W / rows.length) * 0.66);
    rows.forEach((r, i) => {
      const x = (i + 0.5) * (W / rows.length);
      const up = r.c >= r.o;
      g.strokeStyle = up ? "#12b76a" : "#f04438";
      g.fillStyle = up ? "#12b76a" : "#f04438";
      g.beginPath(); g.moveTo(x, y(r.h)); g.lineTo(x, y(r.l)); g.stroke();
      const yo = y(r.o), yc = y(r.c);
      g.fillRect(x - bw / 2, Math.min(yo, yc), bw, Math.max(1, Math.abs(yc - yo)));
    });
  }, [rows]);

  const last = rows[rows.length - 1];
  const first = rows[0];
  const change = last && first ? ((last.c / first.o - 1) * 100) : 0;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {INTERVALS.map(([k, lab]) => (
          <button key={k} onClick={() => setIv(k)}
            className={`rounded-full px-2.5 py-0.5 text-theme-xs font-medium ${iv === k
              ? "bg-brand-500 text-white" : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-400"}`}>
            {lab}
          </button>
        ))}
        {!!rows.length && (
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">
            {rows.length} bars · last {last.c} ·{" "}
            <span className={change >= 0 ? "text-success-600" : "text-error-500"}>
              {change >= 0 ? "+" : ""}{change.toFixed(2)}% over the window
            </span>
          </span>
        )}
      </div>
      {err && <p className="text-theme-sm text-error-500">chart unavailable: {err}</p>}
      {!err && !rows.length && <p className="text-theme-sm text-gray-500 dark:text-gray-400">no candles for this contract</p>}
      <canvas ref={ref} className="h-48 w-full" />
    </div>
  );
}
