import sqlite3, os, json, collections
p = os.path.expanduser('~/.tradingagents/v4/rows.db')
c = sqlite3.connect('file:' + p + '?mode=ro', uri=True)
c.row_factory = sqlite3.Row
BAD = "coin not in ('TWUMC','WUXIBIO')"
b3 = ("older_trades>=20 and newer_trades>=20 and older_profit>0 and newer_profit>0 and real_trades>=20 "
      "and real_profit>0 and months_n>=3 and green=months_n")
rows = [dict(r) for r in c.execute(f"select * from strat where {BAD} and {b3}")]
print("rows", len(rows))
seen = {}
for r in rows:
    k = (r["coin"], r["tf"], r["trades"], round(r["profit"], 4), round(r["real_profit"], 4))
    seen.setdefault(k, []).append(r)
print("distinct trade lists", len(seen))
print("coins", len({r['coin'] for r in rows}))
print("by strategy:", collections.Counter(r["strategy"] for r in rows).most_common())
print("by tf:", collections.Counter(r["tf"] for r in rows))
print("by label (setting+stop+target):", collections.Counter((r["strategy"], r["sl"], r["tp"]) for r in rows).most_common(8))
print("sum real_profit", round(sum(v[0]["real_profit"] for v in seen.values()), 2),
      "real trades", sum(v[0]["real_trades"] for v in seen.values()),
      "profit total", round(sum(v[0]["profit"] for v in seen.values()), 2),
      "trades", sum(v[0]["trades"] for v in seen.values()))
bad10 = {"TWUMC","NANYA","YAGEO","LNG","TWASX","OXY","WUXIBIO","TWDELTA","WINBOND","XP"}
print("on the ten wide-book coins:", sum(1 for r in rows if r["coin"] in bad10))
# persistence: chosen on older half, did it repeat on the newer half?
q = lambda w: c.execute(f"select count(*) from strat where {BAD} and older_trades>=20 and newer_trades>=20 and {w}").fetchone()[0]
op = q("older_profit>0"); both = q("older_profit>0 and newer_profit>0"); allx = q("1=1"); newer = q("newer_profit>0")
print("older>0:", op, "of those newer>0:", both, round(100*both/op,1), "% ; base rate newer>0:", newer, round(100*newer/allx,1), "%")
# loser side too: older<0 -> newer>0
neg = q("older_profit<=0"); negnew = q("older_profit<=0 and newer_profit>0")
print("older<=0 -> newer>0:", negnew, "of", neg, round(100*negnew/neg,1), "%")
# newer-half result of the older-positive group, in dollars per trade
r = c.execute(f"select sum(newer_profit), sum(newer_trades) from strat where {BAD} and older_trades>=20 and newer_trades>=20 and older_profit>0").fetchone()
print("older-positive group on the newer half: $%.2f over %d trades = %.3f per trade" % (r[0], r[1], r[0]/r[1]))
r = c.execute(f"select sum(newer_profit), sum(newer_trades) from strat where {BAD} and older_trades>=20 and newer_trades>=20").fetchone()
print("all on the newer half: $%.2f over %d trades = %.3f per trade" % (r[0], r[1], r[0]/r[1]))
# the same top-10 distinct list
print()
top = sorted(seen.values(), key=lambda v: -v[0]["real_profit"])[:10]
for v in top:
    r = v[0]
    print(f"#{r['id']} {r['coin']} {r['tf']} {r['label']} | {r['trades']} trades {r['win_rate']:.0f}% won, total {r['profit']:+.2f}, real-priced {r['real_trades']} trades {r['real_profit']:+.2f}, older {r['older_profit']:+.2f} newer {r['newer_profit']:+.2f}, months {r['green']}/{r['months_n']} green, worst run {r['worst_run']:.2f} over {r['worst_run_n']}, twins {len(v)-1}")
