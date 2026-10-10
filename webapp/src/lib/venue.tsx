"use client";
/**
 * The exchange's NAME, from the one answer that knows it (`/api/venue`,
 * tradingagents/venue.py). The app moved from MEXC to Gate on Oct 10, 2026
 * ("okay switch to gate from now on"), and a label that still said MEXC over
 * Gate's numbers is the label-must-match-data failure. No component spells an
 * exchange itself (tests/test_the_screen_names_the_exchange.py).
 *
 * Asked once per tab and shared. Until it answers — or if it cannot — a label
 * reads "the exchange", never a guessed name.
 */
import { useEffect, useState } from "react";
import { venueInfo } from "./api";

export const VENUE_UNKNOWN = "the exchange";

let known: string | null = null;
let asking: Promise<string> | null = null;

export function venueName(): Promise<string> {
  if (known) return Promise.resolve(known);
  if (!asking) {
    asking = venueInfo()
      .then((v) => (known = v.name || VENUE_UNKNOWN))
      .catch(() => {
        asking = null;          // ask again next time
        return VENUE_UNKNOWN;
      });
  }
  return asking;
}

export function useVenueName(): string {
  const [name, setName] = useState<string>(known ?? VENUE_UNKNOWN);
  useEffect(() => {
    let live = true;
    venueName().then((v) => { if (live) setName(v); });
    return () => { live = false; };
  }, []);
  return name;
}
