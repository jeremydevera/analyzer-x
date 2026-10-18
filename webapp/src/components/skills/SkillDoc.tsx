"use client";
/** ONE SKILL'S OWN TEXT, opened from its tile on the Claude skills tab.
 *
 * Operator, Oct 17, 2026: *"in claude skills when i click the tile show me
 * the md on how claude do that skill i want detailed"*.
 *
 * Everything shown comes from `/api/claude-skills/{name}`
 * (tradingagents/claude_skills.py `skill_doc`): the whole SKILL.md, every
 * other note in the skill's folder, and the files it works with. The
 * markdown is turned into React elements here - never into raw HTML - so a
 * skill file can only ever be text on this page.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { API_BASE } from "@/lib/api";

type Doc = {
  name: string;
  group: string;
  description: string;
  own_description: string;
  always: boolean;
  path: string;
  markdown: string;
  files: { path: string; bytes: number }[];
  docs: { path: string; markdown: string }[];
  docs_left_out: string[];
};

// ------------------------------------------------------------ inline text
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;

function inline(text: string, key = ""): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const t = m[0];
    const k = `${key}-${i++}`;
    if (t.startsWith("`")) {
      out.push(<code key={k} className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[0.92em] text-gray-800 dark:bg-white/[0.08] dark:text-gray-100">{t.slice(1, -1)}</code>);
    } else if (t.startsWith("**") || t.startsWith("__")) {
      out.push(<strong key={k} className="font-semibold text-gray-900 dark:text-white">{inline(t.slice(2, -2), k)}</strong>);
    } else if (t.startsWith("[")) {
      const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t);
      const href = mm ? mm[2] : "";
      const safe = /^https?:\/\//i.test(href);
      out.push(safe
        ? <a key={k} href={href} target="_blank" rel="noopener noreferrer" className="text-brand-600 underline dark:text-brand-400">{inline(mm ? mm[1] : t, k)}</a>
        : <span key={k} className="text-gray-800 dark:text-gray-200">{inline(mm ? mm[1] : t, k)}{href && <span className="text-gray-400"> ({href})</span>}</span>);
    } else {
      out.push(<em key={k}>{inline(t.slice(1, -1), k)}</em>);
    }
    last = at + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ------------------------------------------------------------ blocks
type Item = { depth: number; ordered: boolean; text: string };

function list(items: Item[], key: string): ReactNode {
  // nest by indentation: deeper items belong to the item before them
  const render = (from: number, depth: number): [ReactNode[], number] => {
    const nodes: ReactNode[] = [];
    let i = from;
    while (i < items.length && items[i].depth >= depth) {
      if (items[i].depth > depth) {
        const [kids, next] = render(i, items[i].depth);
        const Tag = items[i].ordered ? "ol" : "ul";
        nodes.push(<Tag key={`${key}-n${i}`} className={(items[i].ordered ? "list-decimal" : "list-disc") + " ml-5 mt-1 space-y-1"}>{kids}</Tag>);
        i = next;
        continue;
      }
      nodes.push(<li key={`${key}-${i}`}>{inline(items[i].text, `${key}-${i}`)}</li>);
      i++;
    }
    return [nodes, i];
  };
  const [nodes] = render(0, items[0].depth);
  const Tag = items[0].ordered ? "ol" : "ul";
  return <Tag key={key} className={(items[0].ordered ? "list-decimal" : "list-disc") + " ml-5 space-y-1"}>{nodes}</Tag>;
}

function cells(row: string): string[] {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

/** The front block (`---` name / description `---`) is shown above the text
 *  by the panel itself, so it is left out here. */
export function stripFront(md: string): string {
  const m = /^\s*---\s*\n[\s\S]*?\n---\s*(\n|$)/.exec(md);
  return m ? md.slice(m[0].length) : md;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let para: string[] = [];
  let i = 0;
  const flush = () => {
    if (para.length) {
      out.push(<p key={`p${out.length}`} className="leading-relaxed">{inline(para.join(" "), `p${out.length}`)}</p>);
      para = [];
    }
  };
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*(```|~~~)(.*)$/.exec(line);
    if (fence) {
      flush();
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      i++;
      out.push(
        <pre key={`c${out.length}`} className="overflow-x-auto rounded-lg bg-gray-900 p-3 text-[12px] leading-relaxed text-gray-100 dark:bg-black/40">
          <code>{body.join("\n")}</code>
        </pre>);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flush();
      const level = h[1].length;
      const cls = level === 1 ? "mt-2 text-lg font-semibold text-gray-900 dark:text-white"
        : level === 2 ? "mt-4 border-b border-gray-200 pb-1 text-base font-semibold text-gray-900 dark:border-white/[0.08] dark:text-white"
          : "mt-3 text-theme-sm font-semibold text-gray-900 dark:text-white";
      out.push(<div key={`h${out.length}`} role="heading" aria-level={level} className={cls}>{inline(h[2], `h${out.length}`)}</div>);
      i++;
      continue;
    }
    if (/^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(line)) {
      flush();
      out.push(<hr key={`r${out.length}`} className="border-gray-200 dark:border-white/[0.08]" />);
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flush();
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      out.push(
        <div key={`t${out.length}`} className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-[12px]">
            <thead><tr>{head.map((c, k) => <th key={k} className="border-b border-gray-200 px-2 py-1 font-semibold dark:border-white/[0.08]">{inline(c, `th${k}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, n) => <tr key={n}>{r.map((c, k) => <td key={k} className="border-b border-gray-100 px-2 py-1 align-top dark:border-white/[0.05]">{inline(c, `td${n}-${k}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>);
      continue;
    }
    if (/^\s*>/.test(line)) {
      flush();
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(
        <blockquote key={`q${out.length}`} className="border-l-4 border-gray-300 pl-3 text-gray-600 dark:border-white/[0.15] dark:text-gray-300">
          <Markdown text={body.join("\n")} />
        </blockquote>);
      continue;
    }
    const li = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      flush();
      const items: Item[] = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (m) {
          items.push({ depth: m[1].replace(/\t/g, "  ").length, ordered: /\d/.test(m[2]), text: m[3] });
          i++;
        } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) {
          items[items.length - 1].text += " " + lines[i].trim();   // a wrapped item
          i++;
        } else {
          break;
        }
      }
      out.push(list(items, `l${out.length}`));
      continue;
    }
    if (!line.trim()) {
      flush();
      i++;
      continue;
    }
    para.push(line.trim());
    i++;
  }
  flush();
  return <div className="flex flex-col gap-2 text-theme-xs text-gray-700 dark:text-gray-300">{out}</div>;
}

// ------------------------------------------------------------ the panel
function size(b: number): string {
  return b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB`
    : b >= 1024 ? `${Math.round(b / 1024)} KB` : `${b} bytes`;
}

export default function SkillDoc({ name, onClose }: { name: string; onClose: () => void }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [err, setErr] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // one panel per skill (the tab keys it by name), so it starts empty
    let live = true;
    fetch(`${API_BASE}/api/claude-skills/${encodeURIComponent(name)}`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`/api/claude-skills/${name} -> HTTP ${r.status}`);
        return (await r.json()) as Doc;
      })
      .then((d) => { if (live) setDoc(d); })
      .catch((e) => { if (live) setErr(String(e?.message ?? e)); });
    return () => { live = false; };
  }, [name]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[99999] flex items-start justify-center bg-black/40 p-4 sm:p-8"
         onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={`How Claude does ${name}`}
           onClick={(e) => e.stopPropagation()}
           className="flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-xl dark:border-white/[0.08] dark:bg-gray-900">
        <div className="flex items-start justify-between gap-3 border-b border-gray-200 p-4 dark:border-white/[0.08]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <code className="break-all text-theme-sm font-semibold text-gray-900 dark:text-white">{name}</code>
              {doc && <span className="text-theme-xs text-gray-500 dark:text-gray-400">{doc.group}</span>}
              {doc && <span className={"rounded-full px-2 py-0.5 text-[11px] font-medium "
                + (doc.always ? "bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400"
                  : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-400")}>
                {doc.always ? "runs by itself" : "when needed"}</span>}
            </div>
            {doc && <p className="mt-1 text-theme-xs text-gray-600 dark:text-gray-300">{doc.description}</p>}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close"
                  className="rounded-lg border border-gray-300 px-2.5 py-1 text-theme-xs text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-white/[0.05]">
            Close
          </button>
        </div>
        <div className="overflow-y-auto p-4">
          {err && <p className="text-theme-xs text-error-600 dark:text-error-400">Could not read this skill: {err}</p>}
          {!doc && !err && <p className="text-theme-xs text-gray-500 dark:text-gray-400">Loading how Claude does {name}...</p>}
          {doc && (
            <div className="flex flex-col gap-5">
              <div className="rounded-xl bg-gray-50 p-3 text-theme-xs text-gray-600 dark:bg-white/[0.03] dark:text-gray-300">
                <div><span className="font-semibold text-gray-800 dark:text-white/90">The skill&apos;s own summary: </span>{doc.own_description || "(none written)"}</div>
                <div className="mt-1 text-gray-500 dark:text-gray-400">Read from <code>{doc.path}</code> - every word of the file is below.</div>
              </div>
              <Markdown text={stripFront(doc.markdown)} />
              {doc.docs.map((x) => (
                <details key={x.path} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.06]">
                  <summary className="cursor-pointer text-theme-xs font-semibold text-gray-800 dark:text-white/90">
                    Also in this skill: <code>{x.path}</code>
                  </summary>
                  <div className="mt-3"><Markdown text={stripFront(x.markdown)} /></div>
                </details>
              ))}
              {doc.docs_left_out.length > 0 && (
                <p className="text-theme-xs text-gray-500 dark:text-gray-400">
                  Too long to show here (open them in the folder): {doc.docs_left_out.join(", ")}
                </p>
              )}
              {doc.files.length > 0 && (
                <div>
                  <div className="text-theme-xs font-semibold text-gray-800 dark:text-white/90">
                    Files this skill works with ({doc.files.length})
                  </div>
                  <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                    {doc.files.map((f) => (
                      <li key={f.path} className="flex justify-between gap-2 text-[12px] text-gray-600 dark:text-gray-300">
                        <code className="break-all">{f.path}</code>
                        <span className="shrink-0 text-gray-400">{size(f.bytes)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

