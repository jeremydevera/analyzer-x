"use client";
/** Cumulative realised PnL, one point per closed trade.
 *
 * The legend swatch takes the CURVE's colour: it was once hardcoded green
 * while the line was coral because the book was down, and a legend that
 * disagrees with the line it labels is the same fault as a mislabelled total.
 */
import { useEffect, useRef, useState } from "react";
import { fmtMoney, tradeApi } from "@/lib/api";

export default function EquityCurve() {
  const [pts, setPts] = useState<{ ts: number; equity: number; coin: string }[]>([]);
  const [dry, setDry] = useState(false);
  const [err, setErr] = useState("");
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    tradeApi.equity(dry).then((d) => { setPts(d.points); setErr(""); }).catch((e) => setErr(String(e)));
  }, [dry]);

  useEffect(() => {
    const cv = ref.current;
    if (!cv || pts.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d");
    if (!g) return;
    g.scale(dpr, dpr); g.clearRect(0, 0, W, H);
    const ys = pts.map((p) => p.equity).concat([0]);
    const hi = Math.max(...ys), lo = Math.min(...ys);
    const pad = (hi - lo) * 0.12 || 1;
    const y = (v: number) => H - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * H;
    const x = (i: number) => (i / (pts.length - 1)) * W;
    const up = pts[pts.length - 1].equity >= 0;
    const col = up ? "#12b76a" : "#f04438";
    g.strokeStyle = "#98a2b3"; g.setLineDash([3, 3]); g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, y(0)); g.lineTo(W, y(0)); g.stroke();
    g.setLineDash([]);
    g.strokeStyle = col; g.lineWidth = 1.8;
    g.beginPath();
    pts.forEach((p, i) => (i ? g.lineTo(x(i), y(p.equity)) : g.moveTo(x(i), y(p.equity))));
    g.stroke();
    g.lineTo(W, y(0)); g.lineTo(0, y(0)); g.closePath();
    g.fillStyle = up ? "rgba(18,183,106,.10)" : "rgba(240,68,56,.10)";
    g.fill();
  }, [pts]);

  const last = pts.length ? pts[pts.length - 1].equity : 0;
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Equity, every closed trade</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {pts.length} closed trades on the {dry ? "demo" : "live"} book · cumulative{" "}
            <span className={last >= 0 ? "text-success-600" : "text-error-500"}>{fmtMoney(last)}</span>
          </p>
        </div>
        <label className="ml-auto flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
          <input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} className="h-4 w-4 accent-brand-500" />
          demo book
        </label>
      </div>
      {err && <p className="mt-2 text-theme-sm text-error-500">{err}</p>}
      {pts.length < 2
        ? <p className="mt-3 text-theme-sm text-gray-500 dark:text-gray-400">not enough closed trades to draw a curve yet</p>
        : <canvas ref={ref} className="mt-3 h-36 w-full" />}
      <div className="mt-2 flex gap-4 text-theme-xs text-gray-500 dark:text-gray-400">
        <span className="flex items-center gap-1.5">
          <i className={`inline-block h-2 w-2 rounded-full ${last >= 0 ? "bg-success-500" : "bg-error-500"}`} />
          realised, cumulative
        </span>
        <span className="flex items-center gap-1.5"><i className="inline-block h-2 w-2 rounded-full bg-gray-400" />break-even</span>
      </div>
    </div>
  );
}
