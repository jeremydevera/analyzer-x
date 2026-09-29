"use client";
/** An open tab picks up a new build of the screen by itself.
 *
 *  Operator, Sep 29, 2026: *"again why is my ui not refreshing, i thought
 *  everyting you change will reflect to web autoamtically since this is
 *  react"*. The NUMBERS on every panel poll the API, but the screen's own
 *  CODE is a production build (`next build` + `next start`), and a tab keeps
 *  the build it loaded until it is reloaded — so a tab open across
 *  `start.py start` kept showing the old tiles and the old pager.
 *
 *  Every 20 s (while visible) this asks `/build-version`; when the server's
 *  build is not the one this tab was built from, the tab reloads — unless
 *  the operator is typing in a field or holds an unsaved edit
 *  (`lib/unsaved`), in which case a bar says so and waits for their click.
 */
import { useEffect, useState } from "react";
import { hasUnsaved } from "@/lib/unsaved";

const MINE = process.env.NEXT_PUBLIC_BUILD_ID ?? "";
const EVERY_MS = 20_000;

function busyTyping(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
    || (el as HTMLElement).isContentEditable;
}

export default function NewVersionReload() {
  const [behind, setBehind] = useState(false);

  useEffect(() => {
    if (!MINE) return;
    let dead = false;
    const check = async () => {
      if (dead || document.hidden) return;
      try {
        const r = await fetch("/build-version", { cache: "no-store" });
        if (!r.ok) return;
        const { build } = (await r.json()) as { build: string };
        if (!build || build === MINE) return;
        if (!hasUnsaved() && !busyTyping()) window.location.reload();
        else setBehind(true);
      } catch {
        /* the site is restarting: ask again next time */
      }
    };
    const t = setInterval(check, EVERY_MS);
    const onVisible = () => { if (!document.hidden) check(); };
    document.addEventListener("visibilitychange", onVisible);
    check();
    return () => {
      dead = true;
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  if (!behind) return null;
  return (
    <div className="fixed inset-x-0 bottom-0 z-[100000] flex flex-wrap items-center justify-center gap-3 bg-brand-500 px-4 py-2 text-theme-sm text-white">
      The screen was updated. It did not reload by itself because you have unsaved changes or are typing.
      <button onClick={() => window.location.reload()}
        className="rounded-lg bg-white px-3 py-1 font-semibold text-brand-600">
        Reload now
      </button>
    </div>
  );
}
