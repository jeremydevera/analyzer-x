/** The build the site is serving NOW, for `NewVersionReload`.
 *
 *  Read from `.next/BUILD_ID` on every request (never inlined), so a tab
 *  opened before `start.py start` rebuilt the site learns that it is behind.
 *  Not under /api: that prefix is proxied to the Python API. */
import { readFileSync } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

export function GET() {
  let build = "";
  try {
    build = readFileSync(path.join(process.cwd(), ".next", "BUILD_ID"), "utf-8").trim();
  } catch {
    build = "";
  }
  return Response.json({ build }, { headers: { "Cache-Control": "no-store" } });
}
