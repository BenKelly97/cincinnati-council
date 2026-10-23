"""One-time rewrite of existing titles and descriptions to the writing rules in
update_pipeline.STYLE_RULES. New items already get those rules when tagged.

Run by .github/workflows/rewrite_text.yml.

  python3 rewrite_text.py --limit 30 --dry-run   test: a fixed random sample, nothing saved
  python3 rewrite_text.py --limit 0               all remaining rows, saved to the CSV

Skipped: registrations, statements and other untagged types; appointments with the
fixed wording; rows with a manual title or description override; rows already done.
A rewritten row gets REWRITE_MARK in its notes, so a later run skips it.
"""
import argparse
import csv
import json
import os
import random
import re

import anthropic

import update_pipeline as up

REWRITE_MARK = "[style rewrite]"
BATCH = 15
RAW_MAX = 1500          # characters of the Legistar title sent per item
# File numbers given a manual title or description (from the history of
# title_overrides.json and summary_overrides.json as of 2026-10-23).
MANUAL_FILES = {"202602776", "202602785"}
# Items from the 2026-10-23 screenshots, always in the test sample.
TEST_FILES = ["202602937", "202602925", "202602905"]


def eligible(row):
    return (row.get("tag_status") == "success"
            and row.get("matter_type") not in up.SKIP_TAG_TYPES
            and up.APPOINTMENT_MARK not in (row.get("notes") or "")
            and REWRITE_MARK not in (row.get("notes") or "")
            and row.get("file_number") not in MANUAL_FILES
            and (row.get("clean_title") or "").strip()
            and (row.get("summary") or "").strip())


def prompt_for(rows):
    lines = []
    for i, r in enumerate(rows):
        raw = re.sub(r"\s+", " ", r.get("raw_title") or "")[:RAW_MAX]
        lines.append(f"{i}|{r['matter_type']}|{r.get('requester', '')}|{raw}"
                     f"|{r['clean_title']}|{r['summary']}")
    return f"""Rewrite the title and description of each Cincinnati City Council item.
Return a JSON array, one object per item: {{"i":index,"t":"title","s":"description"}}
{up.STYLE_RULES}
Base the facts on the Legistar text; correct the current title or description where it disagrees.
Items (index|type|requester|Legistar text|current title|current description):
{chr(10).join(lines)}
JSON array only, no markdown."""


def call(client, rows):
    resp = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=3000,
                                  messages=[{"role": "user", "content": prompt_for(rows)}])
    if resp.stop_reason == "max_tokens":
        raise ValueError("response cut off at max_tokens")
    raw = resp.content[0].text.strip()
    k = raw.find("[")
    data = json.loads(raw[k:raw.rfind("]") + 1] if k >= 0 else raw)
    return data, resp.usage.input_tokens, resp.usage.output_tokens


def usable(t, s):
    """Reject output that breaks the rules badly enough to keep the old text."""
    if not t or not s:
        return "empty"
    if len(t.split()) > 16:
        return "title too long"
    if len(s.split()) > 45:
        return "description too long"
    if re.search(r"lobbyist", t + " " + s, re.I):
        return "says lobbyist"
    return None


def md(x):
    return (x or "").replace("|", "/").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30, help="rows to rewrite; 0 = all remaining")
    ap.add_argument("--dry-run", action="store_true", help="print the results; do not save")
    a = ap.parse_args()

    with open(up.OUTPUT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    todo = [r for r in rows if eligible(r)]
    print(f"{len(todo)} rows eligible for rewrite.")
    if a.dry_run:
        fixed = [r for r in todo if r["file_number"] in TEST_FILES]
        rest = [r for r in todo if r["file_number"] not in TEST_FILES]
        n = max(a.limit - len(fixed), 0) if a.limit else len(rest)
        todo = fixed + random.Random(20261023).sample(rest, min(n, len(rest)))
    else:
        todo.sort(key=lambda r: r.get("intro_date", ""), reverse=True)   # newest first
        if a.limit:
            todo = todo[:a.limit]
    print(f"Rewriting {len(todo)} rows{' (dry run)' if a.dry_run else ''}.")

    client = anthropic.Anthropic(api_key=up.ANTHROPIC_API_KEY)
    tin = tout = 0
    done, kept, pairs = 0, [], []
    for b in range(0, len(todo), BATCH):
        chunk = todo[b:b + BATCH]
        try:
            data, i_t, o_t = call(client, chunk)
            tin, tout = tin + i_t, tout + o_t
        except Exception as e:
            print(f"  batch {b // BATCH + 1}: error ({e}); rows left unchanged")
            kept += [(r["file_number"], "batch error") for r in chunk]
            continue
        got = {d.get("i"): d for d in data if isinstance(d, dict)}
        for i, r in enumerate(chunk):
            d = got.get(i) or {}
            t, s = (d.get("t") or "").strip(), (d.get("s") or "").strip()
            why = usable(t, s)
            if why:
                kept.append((r["file_number"], why))
                continue
            pairs.append((r["file_number"], r["matter_type"], r["clean_title"], t, r["summary"], s))
            if not a.dry_run:
                r["clean_title"], r["summary"] = t, s
                r["notes"] = ((r.get("notes") or "") + " " + REWRITE_MARK).strip()
            done += 1
        cost = tin / 1e6 * up.HAIKU_INPUT_COST + tout / 1e6 * up.HAIKU_OUTPUT_COST
        print(f"  batch {b // BATCH + 1}: {done} rewritten so far, ${cost:.3f}")

    cost = tin / 1e6 * up.HAIKU_INPUT_COST + tout / 1e6 * up.HAIKU_OUTPUT_COST
    per = cost / len(todo) if todo else 0
    eligible_left = sum(1 for r in rows if eligible(r))
    summary = [f"## Title and description rewrite{' (dry run, nothing saved)' if a.dry_run else ''}",
               f"Rewritten: {done}. Kept unchanged: {len(kept)}. "
               f"Tokens: {tin:,} in, {tout:,} out. Cost: ${cost:.4f} (${per:.5f} per row).",
               f"Eligible rows not yet rewritten after this run: {eligible_left:,}; "
               f"estimated cost for those at this rate: ${per * eligible_left:.2f}.", ""]
    if kept:
        summary += ["Kept unchanged: " + ", ".join(f"{fn} ({w})" for fn, w in kept), ""]
    if a.dry_run or len(pairs) <= 200:
        summary += ["| File | Type | Old title | New title | Old description | New description |",
                    "|---|---|---|---|---|---|"]
        summary += [f"| {fn} | {mt} | {md(ot)} | {md(nt)} | {md(os_)} | {md(ns)} |"
                    for fn, mt, ot, nt, os_, ns in pairs]
    text = "\n".join(summary)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")

    if not a.dry_run and done:
        with open(up.OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=up.FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"Saved {done} rewritten rows to {up.OUTPUT_CSV}.")


if __name__ == "__main__":
    main()
