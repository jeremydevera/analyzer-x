"use client";
/** WHICH ROOM A PANEL BELONGS TO (operator, Oct 01, 2026: "when i click auto
 * trade tab, load all the info for all, then i want all the numbers updating
 * in realtime").
 *
 * AutoTradeScreen keeps every room's panels mounted, each inside a
 * <RoomScope>. A panel takes its calls from `useRoomApis()` — the same `api`
 * and `tradeApi` objects, every function bound to the panel's own room
 * (`roomBound`) — so a room behind its tab refreshes ITS numbers, never the
 * room on screen. `active` says whether the room is the one on screen; the
 * shared refresh (`useLiveRefresh`) slows a room behind its tab to
 * BEHIND_MS and refreshes it at once when its tab is clicked. */
import { createContext, useContext, useMemo } from "react";
import { api, roomBound, tradeApi } from "./api";

export type Room = { id: string; active: boolean };
export const RoomContext = createContext<Room | null>(null);

/** A room behind its tab refreshes at most this often. */
export const BEHIND_MS = 15_000;

export function RoomScope({ id, active, children }: { id: string; active: boolean; children: React.ReactNode }) {
  const value = useMemo(() => ({ id, active }), [id, active]);
  return <RoomContext.Provider value={value}>{children}</RoomContext.Provider>;
}

export function useRoom(): Room | null {
  return useContext(RoomContext);
}

/** `api` and `tradeApi`, bound to this panel's room (or unbound outside a
 *  room, exactly as before). */
export function useRoomApis(): { api: typeof api; tradeApi: typeof tradeApi } {
  const room = useRoom();
  const id = room?.id;
  return useMemo(() => (id
    ? { api: roomBound(api, id), tradeApi: roomBound(tradeApi, id) }
    : { api, tradeApi }), [id]);
}
