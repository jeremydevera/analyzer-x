"use client";
/** The model catalog and its health. A row's percentage is what the provider
 * just answered — never a cached guess — and the provider's own error text is
 * shown verbatim, because that text IS the fix. */
import { useEffect, useState } from "react";
import { modelsApi, ModelRow, PingResult } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import Button from "@/components/ui/button/Button";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const input =
  "h-10 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm text-gray-700 " +
  "placeholder:text-gray-400 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 " +
  "dark:border-gray-700 dark:text-gray-300";

const tone = (pct: number) => (pct >= 100 ? "success" : pct >= 60 ? "warning" : pct > 0 ? "warning" : "error");

export default function ModelsScreen() {
  const [rows, setRows] = useState<ModelRow[]>([]);
  const [presets, setPresets] = useState<string[]>([]);
  const [health, setHealth] = useState<Record<string, PingResult | "testing">>({});
  const [form, setForm] = useState({ model_id: "", preset: "", base_url: "", key_env: "" });
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = () =>
    modelsApi.list()
      .then((d) => { setRows(d.rows); setPresets(d.presets); if (!form.preset) setForm((f) => ({ ...f, preset: d.presets[0] ?? "" })); setErr(""); })
      .catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const test = async (id: string) => {
    setHealth((h) => ({ ...h, [id]: "testing" }));
    try {
      const got = await modelsApi.ping(id);
      setHealth((h) => ({ ...h, [id]: got }));
    } catch (e) {
      setHealth((h) => ({ ...h, [id]: { model_id: id, status: "error", pct: 0, ms: 0, detail: String(e) } }));
    }
  };

  const testAll = () => { rows.forEach((r) => test(r.id)); };

  const add = async () => {
    const got = await modelsApi.add(form);
    setMsg(got.message);
    if (got.ok) { setForm({ model_id: "", preset: presets[0] ?? "", base_url: "", key_env: "" }); load(); }
  };

  const remove = async (id: string) => {
    if (!confirm(`Remove ${id} from the catalog? Analyses already run keep their results.`)) return;
    await modelsApi.remove(id);
    load();
  };

  const tested = rows.filter((r) => typeof health[r.id] === "object");
  const usable = tested.filter((r) => (health[r.id] as PingResult).pct >= 60);

  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Add a model</h3>
        <p className="text-theme-xs text-gray-500 dark:text-gray-400">
          Saved to this PC and available in every analysis dropdown immediately.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input className={`${input} w-56`} placeholder="vendor/model-id" value={form.model_id}
            onChange={(e) => setForm({ ...form, model_id: e.target.value })} aria-label="Model id" />
          <select className={input} value={form.preset} onChange={(e) => setForm({ ...form, preset: e.target.value })} aria-label="Provider">
            {presets.map((p) => <option key={p}>{p}</option>)}
          </select>
          <input className={`${input} w-64`} placeholder="https://host/v1 (openai-compatible only)" value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })} aria-label="Base URL" />
          <input className={`${input} w-44`} placeholder="KEY_ENV_VAR (optional)" value={form.key_env}
            onChange={(e) => setForm({ ...form, key_env: e.target.value })} aria-label="Key env var" />
          <Button size="sm" onClick={add} disabled={!form.model_id}>ADD MODEL</Button>
        </div>
        {msg && <p className="mt-2 text-theme-sm text-gray-600 dark:text-gray-300">{msg}</p>}
      </div>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
          <div>
            <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Model health</h3>
            <p className="text-theme-xs text-gray-500 dark:text-gray-400">
              {rows.length} models · {rows.filter((r) => r.custom).length} added by you ·{" "}
              {tested.length ? `${usable.length} of ${tested.length} tested are usable now` : "none tested yet this visit"}
            </p>
          </div>
          <Button size="sm" className="ml-auto" onClick={testAll}>TEST ALL</Button>
        </div>
        {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
        <div className="max-w-full overflow-x-auto p-2">
          <Table>
            <TableHeader>
              <TableRow>
                {["model", "provider", "endpoint", "key", "health", "latency", "provider's message", ""].map((h) => (
                  <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {rows.map((r) => {
                const h = health[r.id];
                return (
                  <TableRow key={r.id}>
                    <TableCell className="px-3 py-2 font-mono text-theme-xs text-gray-800 dark:text-white/90">
                      {r.id}{r.custom && <span className="ml-1 text-brand-500">·yours</span>}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.label}</TableCell>
                    <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.base_url ?? "provider default"}</TableCell>
                    <TableCell className="px-3 py-2 text-theme-xs">
                      {r.key_env
                        ? <span className={r.key_present ? "text-success-600" : "text-error-500"}>{r.key_present ? `${r.key_env} set` : `${r.key_env} missing`}</span>
                        : <span className="text-gray-400">none needed</span>}
                    </TableCell>
                    <TableCell className="px-3 py-2">
                      {h === "testing" ? <span className="text-theme-xs text-gray-400">testing…</span>
                        : h ? <Badge size="sm" color={tone(h.pct)}>{h.pct}% {h.status}</Badge>
                        : <span className="text-theme-xs text-gray-400">—</span>}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">
                      {typeof h === "object" ? `${h.ms} ms` : "—"}
                    </TableCell>
                    <TableCell className="max-w-md px-3 py-2 text-theme-xs break-words text-gray-500 dark:text-gray-400">
                      {typeof h === "object" ? h.detail : ""}
                    </TableCell>
                    <TableCell className="px-3 py-2">
                      <div className="flex gap-1">
                        <button onClick={() => test(r.id)} className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300">test</button>
                        {r.custom && <button onClick={() => remove(r.id)} className="rounded-lg border border-error-200 px-2 py-1 text-theme-xs text-error-500 hover:bg-error-50">remove</button>}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
