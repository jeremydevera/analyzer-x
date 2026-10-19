/** The marks inside one line of a skill's text — `code`, **bold**, __bold__,
 *  *italic*, _italic_ and [links](https://...) — as plain tokens. SkillDoc
 *  turns them into React elements, never into HTML.
 *
 *  Kept apart from SkillDoc.tsx so a test can run it as it is (Node strips
 *  the types from a .ts file; it cannot read JSX).
 *
 *  AN UNDERSCORE INSIDE A WORD IS PART OF THE WORD (CommonMark; Oct 18,
 *  2026): the skill page of `winning_room_strategy` printed its own name as
 *  "winning" + an italic "room" + "strategy", the underscores gone, and
 *  `practice_backtest_audit` read the same way. An underscore opens or closes
 *  a mark only where the character outside it is not a letter or digit. */
export type InlineToken =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "em"; text: string }
  | { kind: "link"; text: string; href: string };

const MARKS = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;
const WORD = /[A-Za-z0-9]/;

export function inlineTokens(text: string): InlineToken[] {
  const out: InlineToken[] = [];
  const re = new RegExp(MARKS.source, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const at = m.index;
    const t = m[0];
    if (t.startsWith("_")) {
      // the whole run of underscores counts, as in CommonMark: in
      // snake__case__name the "_case_" inside "__case__" is still mid-word
      let s = at;
      while (s > 0 && text[s - 1] === "_") s--;
      let e = at + t.length;
      while (text[e] === "_") e++;
      if (WORD.test(text[s - 1] ?? "") || WORD.test(text[e] ?? "")) {
        re.lastIndex = at + 1;        // not a mark: look again from the next character
        continue;
      }
    }
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    if (t.startsWith("`")) {
      out.push({ kind: "code", text: t.slice(1, -1) });
    } else if (t.startsWith("**") || t.startsWith("__")) {
      out.push({ kind: "strong", text: t.slice(2, -2) });
    } else if (t.startsWith("[")) {
      const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t);
      out.push({ kind: "link", text: mm ? mm[1] : t, href: mm ? mm[2] : "" });
    } else {
      out.push({ kind: "em", text: t.slice(1, -1) });
    }
    last = at + t.length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}
