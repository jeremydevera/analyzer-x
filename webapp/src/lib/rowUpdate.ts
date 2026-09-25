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
  /** the exchange's cost right now was NOT charged, and why (Sep 25, 2026:
   *  a 5:19am New York press turned #9GNPMXFF from 94% to 0 wins) */
  cost_note?: string;
}

// SHORT. Operator, Sep 25, 2026, after reading "Done at Sep 25, 2026 6:37pm —
// re-tested 100 strategies for GPNSTOCK 30m prank; 100 are in the search now
// — the exchange's cost right now is $3.59 a $100 trade — far above …":
// *"when i update this backtest im having unesary long message ... i just
// want short if its done then show 100% done finished at (speficic date and
// time)"*. The line is `100% done — finished at <when>`; everything else the
// job knows (how many strategies, a cost that was not charged) rides in
// `detail`, shown when the line is hovered. A FAILURE still says what failed:
// "100% done" over a job that broke would be a false label.
export function rowUpdateSentence(
  j: RowUpdateJob, when: string,
): { text: string; bad: boolean; detail: string } {
  const what = `${j.pair || "this pair"}${j.signal ? ` ${j.signal}` : ""}`;
  const at = when ? ` at ${when}` : "";
  const done = `100% done — finished${at}`;
  const n = (j.rows ?? 0).toLocaleString("en-US");
  const cost = j.cost_note ? ` · ${j.cost_note}` : "";
  if (j.error) {
    return { text: `Failed${at}: ${j.error}`, bad: true, detail: j.error };
  }
  if (j.index_error && j.index_queued) {
    // measured fine; the searchable table was busy, and the pair is next
    return {
      text: `${done} · shows in the table shortly`,
      bad: false,
      detail: `Re-tested ${n} strategies for ${what}; the table was busy, so `
        + `they are next in line and appear by themselves${cost}`,
    };
  }
  if (j.index_error) {
    return {
      text: `Re-tested${at}, but not saved to the table: ${j.index_error}`,
      bad: true,
      detail: j.index_error,
    };
  }
  if (j.already_current) {
    return {
      text: `${done} · no new candles`,
      bad: false,
      detail: `Already up to date: no new candles for ${what} since the last update${cost}`,
    };
  }
  return {
    text: done,
    bad: false,
    detail: `Re-tested ${n} strategies for ${what}${cost}`,
  };
}
