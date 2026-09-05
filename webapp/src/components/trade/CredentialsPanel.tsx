"use client";
/** MEXC keys: what is loaded, where from, and what it can actually DO.
 *
 * The key VALUE never comes back from the API — only a masked stub — so this
 * panel can show which key is loaded without being able to leak it. "Can rest
 * a stop" is the row that matters: reading a balance proves nothing about
 * whether a position can be protected (rule 14).
 */
import { useEffect, useState } from "react";
import { CredStatus, Preflight, tradeApi } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import Button from "@/components/ui/button/Button";

const input =
  "h-10 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm text-gray-700 " +
  "placeholder:text-gray-400 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 " +
  "dark:border-gray-700 dark:text-gray-300";

const CHECKS: [keyof Preflight, string][] = [
  ["credentials", "Credentials present"],
  ["read_assets", "Read account balance"],
  ["read_positions", "Read open positions"],
  ["order_permission", "Permission to place orders"],
  ["can_rest_stop", "Rest a stop on MEXC's servers"],
];

export default function CredentialsPanel() {
  const [st, setSt] = useState<CredStatus | null>(null);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [probe, setProbe] = useState<Preflight | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const load = () => tradeApi.creds().then((d) => { setSt(d); setErr(""); }).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const save = async () => {
    setBusy("save");
    try { setSt(await tradeApi.credsSave(key, secret)); setKey(""); setSecret(""); }
    catch (e) { setErr(String(e)); } finally { setBusy(""); }
  };
  const forget = async () => {
    if (!confirm("Forget the saved keys?\n\nThe file on this PC is deleted. A key exported in your shell would still apply, and the runner keeps using whatever is loaded until it restarts.")) return;
    setBusy("forget");
    try { setSt(await tradeApi.credsForget()); } catch (e) { setErr(String(e)); } finally { setBusy(""); }
  };
  const test = async () => {
    setBusy("test"); setProbe(null);
    try { setProbe(await tradeApi.credsTest()); } catch (e) { setErr(String(e)); } finally { setBusy(""); }
  };

  return (
    <div className="min-w-0 rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">MEXC keys</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {st
              ? st.has_credentials
                ? <>loaded from <b>{st.source}</b> · key {st.key_fingerprint} · secret {st.secret_fingerprint}</>
                : "no credentials loaded — the runner cannot place or protect a trade"
              : "reading…"}
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" disabled={busy === "test"} onClick={test}>
            {busy === "test" ? "talking to MEXC…" : "TEST CONNECT"}
          </Button>
          {st?.stored_on_disk && (
            <Button size="sm" variant="outline" disabled={busy === "forget"} onClick={forget}>FORGET SAVED KEYS</Button>
          )}
        </div>
      </div>

      {st?.stored_on_disk && (
        <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
          stored at {st.store_path} · permissions {st.file_mode}{" "}
          {st.file_mode_ok
            ? <span className="text-success-600">(only you can read it)</span>
            : <span className="text-error-500">— readable by others, fix with chmod 600</span>}
        </p>
      )}
      {err && <p className="mt-2 text-theme-sm text-error-500">{err}</p>}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">API key
          <input className={`${input} w-72`} type="password" autoComplete="off" value={key}
            onChange={(e) => setKey(e.target.value)} placeholder="paste to replace" /></label>
        <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">API secret
          <input className={`${input} w-72`} type="password" autoComplete="off" value={secret}
            onChange={(e) => setSecret(e.target.value)} placeholder="paste to replace" /></label>
        <Button size="sm" disabled={!key || !secret || busy === "save"} onClick={save}>SAVE KEYS</Button>
      </div>

      {probe && (
        <div className="mt-4 flex flex-col gap-1">
          {CHECKS.map(([k, label]) => {
            const v = probe[k];
            return (
              <div key={String(k)} className="flex items-center gap-2 text-theme-sm">
                <Badge size="sm" color={v === true ? "success" : v === false ? "error" : "light"}>
                  {v === true ? "PASS" : v === false ? "FAIL" : "UNKNOWN"}
                </Badge>
                <span className="text-gray-700 dark:text-gray-300">{label}</span>
              </div>
            );
          })}
          {probe.can_rest_stop === false && (
            <p className="mt-1 text-theme-sm text-error-500">
              This key cannot rest a stop at the exchange. A position opened with it would sit unprotected — do not arm real money until this passes.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
