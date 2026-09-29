"use client";
/** The terminal. The positions table owns its own fetch (it must poll faster
 * than the ribbon and it carries the close control), and a close bumps `tick`
 * so the ribbon's totals re-read instead of showing a position that is gone. */
import { useEffect, useState } from "react";
import { LATE_MS, begin } from "@/lib/loading";
import LoadingOverlay, { useWaitlist } from "./LoadingCard";
import SummaryRibbon from "./SummaryRibbon";
import PositionsPanel from "./PositionsPanel";
import StrategiesGrid from "./StrategiesGrid";
import WatcherPanel from "./WatcherPanel";
import PnlPanel from "./PnlPanel";
import FeedPanel from "./FeedPanel";
import CredentialsPanel from "./CredentialsPanel";
import TradeHistory from "./TradeHistory";
import { api, PROFILES, RoomInfo, setProfile } from "@/lib/api";
import { rules } from "./WatcherPanel";

const ROOM_KEY = "ta-auto-trade-room";

/** The room the screen opens on: the one last picked on this browser, else
 *  Main. Applied to every request BEFORE any panel mounts and fetches. */
function firstRoom(): string {
  let id = "main";
  try {
    const got = typeof window !== "undefined" ? window.localStorage.getItem(ROOM_KEY) : null;
    if (got && PROFILES.some((p) => p.id === got)) id = got;
  } catch { /* storage blocked: Main */ }
  setProfile(id);
  return id;
}

export default function AutoTradeScreen() {
  // FOLDER TABS, ONE ROOM EACH (operator, Sep 29, 2026: "when i switch to
  // B52662ED i should see its own tiles, own live trade, own demo trade, own
  // calendar pnl, in short it has its own room/ profile"). Every panel below
  // is REMOUNTED on a switch (`key={room}`), so nothing a panel holds from
  // one room can be drawn in another.
  // null until the browser has read the saved room: the server's first frame
  // cannot see it, and panels must not fetch Main's data on the way there
  const [room, setRoom] = useState<string | null>(null);
  useEffect(() => { setRoom(firstRoom()); }, []);
  const pick = (id: string) => {
    setProfile(id);
    try { window.localStorage.setItem(ROOM_KEY, id); } catch { /* blocked */ }
    setRoom(id);
  };
  // THE "i" BESIDE EACH TAB (operator, Sep 29, 2026: "put i icon beside each
  // tab id when i click it show pop up on what's the criteria"): the room's
  // rules as its own watcher runs them, read when the popup opens.
  const [info, setInfo] = useState<string | null>(null);
  const [rooms, setRooms] = useState<RoomInfo[] | null>(null);
  const [infoErr, setInfoErr] = useState("");
  const openInfo = (id: string) => {
    if (info === id) { setInfo(null); return; }
    setInfo(id);
    setInfoErr("");
    api.profiles().then((d) => setRooms(d.profiles)).catch((e) => setInfoErr(String(e)));
  };
  useEffect(() => {
    if (!info) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) { if (e.key === "Escape") setInfo(null); return; }
      const t = e.target as HTMLElement | null;
      if (!t?.closest("[data-room-info]")) setInfo(null);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [info]);
  const [tick, setTick] = useState(0);
  const bump = () => setTick((t) => t + 1);
  // the watch SUBSCRIBES first, begin() fires second — effects run in the
  // order the hooks are declared, and the other order left the screen
  // unblurred for its first second (begin's notify hit zero listeners, so
  // the overlay waited for the 1s tick — measured 355ms names=0, 1365ms
  // names=7 on Sep 09, 2026)
  const waitlist = useWaitlist();
  // the spinner card's watchlist — each panel reports when its data lands.
  // `started` covers the FIRST paint: the server-rendered frame has an empty
  // watchlist (begin runs in an effect), and without it the screen flashed
  // sharp for ~1s before the blur landed (measured 396ms, Sep 09, 2026)
  const [started, setStarted] = useState(false);
  useEffect(() => {
    begin(["summary", "positions", "strategies", "MEXC keys",
           "trade history", "profit", "runner feed"]);
    setStarted(true);
  }, []);
  // BLURRED until fully loaded (the operator's design) — but a name stuck
  // past LATE_MS drops the blur: the loaded panels are usable and the stuck
  // one is red, on the overlay and in its own panel. Frosted glass must
  // never become a lock.
  const blurred = !started
    || (waitlist.length > 0 && waitlist.every((w) => w.waitedMs <= LATE_MS));
  return (
    <div className="relative">
      <div role="tablist" aria-label="Trading rooms"
           className="mb-4 flex flex-wrap gap-1 border-b border-gray-200 dark:border-gray-700">
        {PROFILES.map((p) => {
          const r = rooms?.find((x) => x.id === p.id);
          return (
          <div key={p.id} data-room-info className={`relative -mb-px flex items-center rounded-t-lg border ${room === p.id
            ? "border-gray-200 border-b-white bg-white dark:border-gray-700 dark:border-b-gray-900 dark:bg-gray-900"
            : "border-transparent"}`}>
            <button role="tab" type="button" aria-selected={room === p.id}
              onClick={() => pick(p.id)}
              className={`py-2 pl-4 pr-1.5 text-theme-sm font-medium ${room === p.id
                ? "text-brand-600 dark:text-brand-400"
                : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"}`}>
              {p.name}
            </button>
            <button type="button" onClick={() => openInfo(p.id)}
              aria-label={`What ${p.name} switches on and off`} aria-expanded={info === p.id}
              className="mr-2 flex h-5 w-5 items-center justify-center rounded-full border border-gray-300 text-[11px] font-semibold italic text-gray-500 hover:border-brand-500 hover:text-brand-600 dark:border-gray-600 dark:text-gray-400">
              i
            </button>
            {info === p.id && (
              <div role="dialog" aria-label={`${p.name} rules`}
                className="absolute left-0 top-full z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-gray-200 bg-white p-4 text-theme-xs shadow-lg dark:border-gray-700 dark:bg-gray-900">
                <p className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{p.name} — its rules</p>
                {infoErr && <p className="mt-2 text-error-500">{infoErr}</p>}
                {!r && !infoErr && <p className="mt-2 text-gray-400">reading…</p>}
                {r && (
                  <>
                    <p className="mt-1 text-gray-500 dark:text-gray-400">
                      Smart Watcher <b className={r.mode === "act" ? "text-success-600" : "text-gray-500"}>{r.mode === "act" ? "ON" : r.mode === "preview" ? "PREVIEW" : "OFF"}</b>
                      {" · "}real money <b className={r.live ? "text-error-500" : "text-gray-500"}>{r.live ? "ON" : "off"}</b>
                      {" · "}{r.rows} row{r.rows === 1 ? "" : "s"} switched on
                    </p>
                    <ul className="mt-2 flex list-disc flex-col gap-1 pl-4 text-gray-700 dark:text-gray-300">
                      {rules(r.cfg, r.window_days, r.live).map((t) => <li key={t}>{t}</li>)}
                    </ul>
                  </>
                )}
              </div>
            )}
          </div>
          );
        })}
      </div>
      <LoadingOverlay waitlist={waitlist} />
      {room && <div key={room} aria-busy={waitlist.length > 0}
           className={`flex min-w-0 flex-col gap-5 ${blurred
             ? "pointer-events-none select-none blur-sm"
             : ""}`}>
      <SummaryRibbon key={`ribbon-${tick}`} onChanged={bump} />
      <PositionsPanel onChanged={bump} />
      <StrategiesGrid />
      <WatcherPanel />
      <CredentialsPanel />
      <TradeHistory />
      <PnlPanel />
      <FeedPanel />
      </div>}
    </div>
  );
}
