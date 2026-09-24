// What a row's UPDATE THIS BACKTEST button says once its job has ENDED.
//
// RCA-2026-09-24-K. The operator pressed it on #AJX2ZPQX (CAKE 1h zscore20)
// and read, in green, "CAKE 1h · zscore20: 200 row(s), 220 indexed" — the
// job's own log line, printed word for word. It never said "done", never said
// when, and "row(s)" / "indexed" are programmer words, so a finished update
// could not be told from a running one: *"is it loading or done"*.
//
// One sentence per ending, every word derived from the job's own fields (the
// label-must-match-data rule), and the time it ended passed in already
// formatted by the project's one date formatter (`fmtWhen`). No imports, so a
// test can run this exact file under node.

export interface RowUpdateJob {
  error?: string | null;
  index_error?: string;
  index_queued?: boolean;
  already_current?: boolean;
  rows?: number;
  indexed?: number;
  pair?: string;
  signal?: string;
}

export function rowUpdateSentence(
  j: RowUpdateJob, when: string,
): { text: string; bad: boolean } {
  const what = `${j.pair || "this pair"}${j.signal ? ` ${j.signal}` : ""}`;
  const at = when ? ` at ${when}` : "";
  if (j.error) {
    return { text: `Failed${at}: ${j.error}`, bad: true };
  }
  if (j.index_error && j.index_queued) {
    // measured fine; the searchable table was busy, and the pair is next
    return {
      text: `Re-tested${at}, but not in the search yet — it is next in line `
        + `and appears by itself when the table frees up`,
      bad: false,
    };
  }
  if (j.index_error) {
    return {
      text: `Re-tested${at}, but it could not be put in the search: ${j.index_error}`,
      bad: true,
    };
  }
  if (j.already_current) {
    return {
      text: `Done${at} — already up to date: no new candles for ${what} since the last update`,
      bad: false,
    };
  }
  const n = (j.rows ?? 0).toLocaleString("en-US");
  const k = (j.indexed ?? 0).toLocaleString("en-US");
  return {
    text: `Done${at} — re-tested ${n} strategies for ${what}; ${k} are in the search now`,
    bad: false,
  };
}
