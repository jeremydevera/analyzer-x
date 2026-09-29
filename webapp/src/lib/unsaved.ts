/** Who on the screen holds an edit that is not saved yet.
 *
 *  Read by `NewVersionReload` (Sep 29, 2026): a new build of the screen
 *  reloads every open tab by itself, but NEVER over an unsaved draft — the
 *  strategies grid's margins and switches wait for SAVE CONFIG, and a reload
 *  would throw them away without a word. */
const holders = new Set<string>();

export function markUnsaved(who: string, on: boolean): void {
  if (on) holders.add(who);
  else holders.delete(who);
}

export function hasUnsaved(): boolean {
  return holders.size > 0;
}
