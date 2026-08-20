"use client";
/** Run the analyst pipeline on a ticker. The run is a detached process, so
 * closing this page does not stop it — reopening picks the run back up from
 * its progress file. Stage status is derived from whether each report
 * actually exists, never from a timer. */
import { useCallback, useEffect, useState } from "react";
import { analysisApi, AnalysisRun, ModelRow, modelsApi, RunListRow, SocialSources } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import Button from "@/components/ui/button/Button";

const ANALYSTS = [
  ["market", "Market"], ["social", "Sentiment"], ["news", "News"], ["fundamentals", "Fundamentals"],
] as const;

const input =
  "h-10 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm text-gray-700 " +
  "placeholder:text-gray-400 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 " +
  "dark:border-gray-700 dark:text-gray-300";

const today = () => new Date().toISOString().slice(0, 10);

export default function AnalysisScreen() {
  const [models, setModels] = useState<ModelRow[]>([]);
  const [ticker, setTicker] = useState("");
  const [date, setDate] = useState(today());
  const [model, setModel] = useState("");
  const [asset, setAsset] = useState("stock");
  const [picked, setPicked] = useState<string[]>(ANALYSTS.map((a) => a[0]));
  const [debate, setDebate] = useState(1);
  const [social, setSocial] = useState<SocialSources | null>(null);
  const [source, setSource] = useState("stocktwits");
  const [keywords, setKeywords] = useState("");
  const [risk, setRisk] = useState(1);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [recent, setRecent] = useState<RunListRow[]>([]);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string>("");

  useEffect(() => {
    modelsApi.list().then((d) => { setModels(d.rows); if (!model && d.rows[0]) setModel(d.rows[0].id); }).catch((e) => setErr(String(e)));
    analysisApi.runs().then((d) => setRecent(d.rows)).catch(() => {});
    analysisApi.socialSources().then((d) => { setSocial(d); setSource(d.default); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const poll = useCallback((id: string) => {
    analysisApi.status(id).then((d) => { setRun(d); setErr(d.error ?? ""); }).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!runId) return;
    poll(runId);
    const t = setInterval(() => poll(runId), 4000);
    return () => clearInterval(t);
  }, [runId, poll]);

  useEffect(() => {
    if (run && !run.running) analysisApi.runs().then((d) => setRecent(d.rows)).catch(() => {});
  }, [run?.running]);   // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setErr(""); setRun(null);
    try {
      const got = await analysisApi.start({
        ticker: ticker.trim().toUpperCase(), trade_date: date, model,
        analysts: picked, debate_rounds: debate, risk_rounds: risk, asset_type: asset,
        social_source: source,
        twitter_keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
      });
      setRunId(got.run_id);
    } catch (e) { setErr(String(e)); }
  };

  const stop = async () => { if (runId && confirm("Stop this analysis run?")) { await analysisApi.stop(runId); poll(runId); } };

  const done = run?.stages.filter((s) => s.status === "done").length ?? 0;
  const total = run?.stages.length ?? 0;
  const runningStage = run?.stages.find((s) => s.status === "running")?.label;
  const reports = Object.entries(run?.reports ?? {});

  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Run an analysis</h3>
        <p className="text-theme-xs text-gray-500 dark:text-gray-400">
          The run is its own process — leaving this page does not stop it, and coming back picks it up.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">ticker
            <input className={`${input} w-28`} placeholder="AAPL" value={ticker} onChange={(e) => setTicker(e.target.value)} /></label>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">date
            <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} /></label>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">asset
            <select className={input} value={asset} onChange={(e) => setAsset(e.target.value)}>
              <option value="stock">stock</option><option value="crypto">crypto</option>
            </select></label>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">model
            <select className={`${input} w-56`} value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.id} · {m.label}</option>)}
            </select></label>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">debate rounds
            <input type="number" min={1} max={4} className={`${input} w-20`} value={debate} onChange={(e) => setDebate(Number(e.target.value))} /></label>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">risk rounds
            <input type="number" min={1} max={4} className={`${input} w-20`} value={risk} onChange={(e) => setRisk(Number(e.target.value))} /></label>
        </div>
        {picked.includes("social") && (
          <div className="mt-3 flex flex-wrap items-end gap-2 rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
            <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">where the Sentiment Analyst reads posts
              <select className={`${input} w-52`} value={source} onChange={(e) => setSource(e.target.value)}>
                {(social?.sources ?? []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select></label>
            <span className="pb-2 text-theme-xs text-gray-500 dark:text-gray-400">
              {social?.sources.find((s) => s.id === source)?.note}
            </span>
            {source !== "stocktwits" && (
              <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">extra X search terms (comma separated)
                <input className={`${input} w-72`} placeholder="Meralco, rate hike ERC" value={keywords}
                  onChange={(e) => setKeywords(e.target.value)} /></label>
            )}
            {source !== "stocktwits" && social && !social.x_key_present && (
              <span className="pb-2 text-theme-xs font-medium text-error-500">
                {social.x_key_env} is not set — X would return nothing. Add the key or pick StockTwits.
              </span>
            )}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">analysts:</span>
          {ANALYSTS.map(([key, label]) => (
            <button key={key} onClick={() => setPicked((p) => p.includes(key) ? p.filter((k) => k !== key) : [...p, key])}
              className={`rounded-full px-3 py-1 text-theme-xs font-medium transition ${
                picked.includes(key) ? "bg-brand-500 text-white" : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-400"}`}>
              {label}
            </button>
          ))}
          <div className="ml-auto flex gap-2">
            <Button size="sm" onClick={start} disabled={!ticker.trim() || !picked.length || !!run?.running}>START ANALYSIS</Button>
            {run?.running && <Button size="sm" variant="outline" onClick={stop}>STOP</Button>}
          </div>
        </div>
        {err && <p className="mt-2 text-theme-sm text-error-500">{err}</p>}
      </div>

      {run && (
        <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-theme-sm text-brand-600 dark:text-brand-400">{run.run_id}</span>
            <Badge size="sm" color={run.running ? "info" : run.error ? "error" : "success"}>
              {run.running ? `running · ${done}/${total} stages` : run.error ? "failed" : `finished · ${done}/${total} stages`}
            </Badge>
            {run.running && runningStage && <span className="text-theme-xs text-gray-500 dark:text-gray-400">now: {runningStage}</span>}
            {run.spec?.model && <span className="text-theme-xs text-gray-500 dark:text-gray-400">{run.spec.ticker} · {run.spec.trade_date} · {run.spec.model}</span>}
            {run.spec?.social_source && (
              <Badge size="sm" color={run.spec.social_source === "stocktwits" ? "light" : "warning"}>
                social: {run.spec.social_source}
                {run.spec.twitter_keywords?.length ? ` +${run.spec.twitter_keywords.length} X terms` : ""}
              </Badge>
            )}
          </div>
          <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.06]">
            <div className={`h-full rounded-full transition-all ${run.error ? "bg-error-500" : run.running ? "bg-brand-500" : "bg-success-500"}`}
              style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {run.stages.map((s) => (
              <span key={s.label} className={`rounded-lg px-2.5 py-1 text-theme-xs ${
                s.status === "done" ? "bg-success-50 text-success-700 dark:bg-success-500/15"
                : s.status === "running" ? "bg-brand-50 text-brand-600 dark:bg-brand-500/15"
                : "bg-gray-100 text-gray-500 dark:bg-white/[0.05] dark:text-gray-400"}`}>
                {s.status === "done" ? "✓ " : s.status === "running" ? "• " : ""}{s.label}
              </span>
            ))}
          </div>
          {run.error && <p className="mt-3 rounded-lg bg-error-50 px-3 py-2 text-theme-sm text-error-600 dark:bg-error-500/10">{run.error}</p>}
          {run.decision && (
            <div className="mt-4 rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
              <p className="text-theme-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Final decision</p>
              <p className="mt-1 whitespace-pre-wrap text-theme-sm text-gray-800 dark:text-white/90">{run.decision}</p>
            </div>
          )}
          <div className="mt-4 flex flex-col gap-2">
            <p className="text-theme-xs text-gray-500 dark:text-gray-400">
              {reports.length} report{reports.length === 1 ? "" : "s"} written so far
            </p>
            {reports.map(([label, text]) => (
              <div key={label} className="rounded-xl border border-gray-200 dark:border-white/[0.08]">
                <button onClick={() => setOpen(open === label ? "" : label)}
                  className="flex w-full items-center justify-between px-4 py-2.5 text-left text-theme-sm font-medium text-gray-800 dark:text-white/90">
                  {label}
                  <span className="text-theme-xs text-gray-400">{text.length.toLocaleString()} chars {open === label ? "▲" : "▼"}</span>
                </button>
                {open === label && (
                  <pre className="max-h-96 overflow-auto whitespace-pre-wrap border-t border-gray-100 px-4 py-3 text-theme-xs leading-relaxed text-gray-600 dark:border-white/[0.06] dark:text-gray-300">{text}</pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">Recent runs</h3>
        <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
          {recent.length} on this Mac · {recent.filter((r) => r.running).length} still running
        </p>
        <div className="flex flex-col gap-1 p-3">
          {recent.map((r) => (
            <button key={r.run_id} onClick={() => setRunId(r.run_id)}
              className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-gray-50 dark:hover:bg-white/[0.03]">
              <span className="font-mono text-theme-xs text-brand-600 dark:text-brand-400">{r.run_id}</span>
              <span className="text-theme-xs text-gray-500 dark:text-gray-400">{r.model}</span>
              {r.running ? <Badge size="sm" color="info">running</Badge>
                : r.error ? <Badge size="sm" color="error">failed</Badge>
                : <Badge size="sm" color="success">done</Badge>}
              {r.started_at && <span className="text-theme-xs text-gray-400">{new Date(r.started_at * 1000).toLocaleString()}</span>}
            </button>
          ))}
          {!recent.length && <p className="px-2 py-3 text-theme-sm text-gray-500 dark:text-gray-400">No runs on this Mac yet.</p>}
        </div>
      </div>
    </div>
  );
}
