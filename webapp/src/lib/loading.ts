/** Who on this screen has loaded, for the ONE spinner card at the top.
 *
 * Operator, Sep 09, 2026: *"Why not just show a loading spinning icon thats
 * the simplest, then under that icon show whats being loaded so im aware"* —
 * after an API restart's dark seconds painted every panel red at once.
 *
 * Each panel calls `markReady(name)` when its FIRST data lands. The card
 * subscribes and lists the names still missing. `begin()` resets the slate on
 * every mount, so navigating away and back starts a fresh watch.
 */

const ready = new Set<string>();
const startedAt = new Map<string, number>();
const listeners = new Set<() => void>();

export function begin(names: string[]): void {
  ready.clear();
  startedAt.clear();
  const now = Date.now();
  for (const n of names) startedAt.set(n, now);
  for (const l of listeners) l();
}

export function markReady(name: string): void {
  if (ready.has(name)) return;
  ready.add(name);
  for (const l of listeners) l();
}

/** names not loaded yet, with how long they have been waiting (ms) */
export function pending(): { name: string; waitedMs: number }[] {
  const now = Date.now();
  return [...startedAt.entries()]
    .filter(([n]) => !ready.has(n))
    .map(([name, t0]) => ({ name, waitedMs: now - t0 }));
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** grey "still loading" turns red after this — a wait is honest for a while,
 *  then it is a failure wearing a spinner */
export const LATE_MS = 30_000;
