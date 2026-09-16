"use client";

/**
 * The demo / live W/L cell: a solid donut, the win rate in the hole,
 * the two counts beside it.
 *
 * Chosen by the operator on `Sep 16, 2026` from twenty drawings of the same
 * cell ("badge on a soft disc"), after asking for green/red and for the win
 * rate percentage. What it replaced was `2/1 67%` in flat text.
 *
 * The soft disc is GONE, same day: at a 42px box the disc reached 21px while
 * the ring stopped at 17px, so 4px of `#ecfdf3` showed all the way round and
 * read as a rendering fault rather than a tint — *"why does the mini graph has
 * blur border"*, then *"i dont want it i just want solid"*. The box is 36px
 * now, which is the ring and nothing else. Do not put a halo, a glow or a
 * shadow back behind it.
 *
 * Three things here are load-bearing, not decoration:
 *
 * - **The counts are written out, never colour alone.** `#039855` against
 *   `#f04438` reads at ΔE 8.3 for a deutan reader, which clears the floor but
 *   only just; the `2W` / `1L` text is what makes the cell safe, and a ring
 *   with no label beside it would not be.
 * - **A gap between the two arcs.** Green and red must not share an edge, or
 *   the boundary is the only thing carrying the split.
 * - **A donut cannot say how many trades it is made of.** 2W/0L and 1W/0L are
 *   both a full green ring, so the counts do that job. `title` carries the
 *   whole sentence for anyone who hovers.
 */
const R = 14.5;          // ring radius
const SW = 5;            // ring thickness
const C = 2 * Math.PI * R;
const GAP = 2.5;         // surface gap between the green and the red arc
const BOX = 36;          // just big enough for the ring — no halo around it

export default function WinBadge({ wins, losses }: { wins: number; losses: number }) {
  const n = wins + losses;
  if (n <= 0) return <span className="text-gray-400">—</span>;
  const frac = wins / n;
  const pctText = `${Math.round(100 * frac)}%`;
  const arc = Math.max(0.5, frac * C - GAP);

  return (
    <div className="flex items-center gap-1.5">
      <svg width={BOX} height={BOX} viewBox={`0 0 ${BOX} ${BOX}`} className="shrink-0"
           role="img" aria-label={`${wins} won, ${losses} lost, ${pctText} win rate`}>
        {/* losses underneath, wins on top — one full ring plus one arc is
            fewer moving parts than two arcs that have to meet exactly */}
        <circle cx={BOX / 2} cy={BOX / 2} r={R} fill="none" strokeWidth={SW}
                className={losses > 0 ? "stroke-error-500" : "stroke-success-600"} />
        {wins > 0 && losses > 0 && (
          <g transform={`rotate(-90 ${BOX / 2} ${BOX / 2})`}>
            <circle cx={BOX / 2} cy={BOX / 2} r={R} fill="none" strokeWidth={SW}
                    strokeLinecap="round" className="stroke-success-600"
                    strokeDasharray={`${arc} ${C - arc}`} strokeDashoffset={-GAP / 2} />
          </g>
        )}
        <text x={BOX / 2} y={BOX / 2} textAnchor="middle" dominantBaseline="central"
              className="fill-gray-800 dark:fill-gray-100"
              style={{ fontSize: 9.5, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
          {pctText}
        </text>
      </svg>
      <span className="flex flex-col leading-tight text-[10px] tabular-nums">
        <span className="font-semibold text-success-600">{wins}W</span>
        <span className="font-semibold text-error-500">{losses}L</span>
      </span>
    </div>
  );
}
