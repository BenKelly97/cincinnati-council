"""One-time rewrite of existing titles and descriptions to the writing rules in
update_pipeline.STYLE_RULES. New items already get those rules when tagged.

Run by .github/workflows/rewrite_text.yml.

  python3 rewrite_text.py --limit 30 --dry-run   test: a fixed random sample, nothing saved
  python3 rewrite_text.py --limit 0               all remaining rows, saved to the CSV
  --model sonnet-5-5 (default) or haiku-4-5

Skipped: registrations, statements and other untagged types; appointments with the
fixed wording; rows with a manual title or description override; rows already done.
A rewritten row gets REWRITE_MARK in its notes, so a later run skips it, unless its
title or description is over TITLE_MAX or DESC_MAX words.
"""
import argparse
import csv
import json
import os
import random
import re

import anthropic

import attachments as att
import update_pipeline as up

REWRITE_MARK = "[style rewrite]"
BATCH = 15
RAW_MAX = 4000          # characters of the Legistar title sent per item
# Model choice: (API model id, $ per million input tokens, $ per million output tokens).
# Sonnet 5.5 rates are from a third-party listing; the run reports measured cost either way.
MODELS = {
    "haiku-4-5":  ("claude-haiku-4-5-20251001", 1.00, 5.00),
    "sonnet-5-5": ("claude-sonnet-5-5", 2.00, 10.00),
}
# File numbers given a manual title or description (from the history of
# title_overrides.json and summary_overrides.json as of 2026-10-23).
MANUAL_FILES = {"202602776", "202602785"}
# Items from the 2026-10-23 screenshots, always in the test sample.
TEST_FILES = ["202602937", "202602925", "202602905"]


# Hard limits on output. The writing rules ask for 12 and 30 words; one and five
# words of slack keep near misses. Longer output is rejected, and a rewritten row
# whose text is over these limits is rewritten again on the next run.
TITLE_MAX = 13
DESC_MAX = 35


def too_long(t, s):
    return len((t or "").split()) > TITLE_MAX or len((s or "").split()) > DESC_MAX


def eligible(row):
    """Rows not yet rewritten, plus rewritten rows whose text is over the limits."""
    notes = row.get("notes") or ""
    return (row.get("tag_status") == "success"
            and row.get("matter_type") not in up.SKIP_TAG_TYPES
            and up.APPOINTMENT_MARK not in notes
            and row.get("file_number") not in MANUAL_FILES
            and (row.get("clean_title") or "").strip()
            and (row.get("summary") or "").strip()
            and (REWRITE_MARK not in notes or too_long(row["clean_title"], row["summary"])))


def prompt_for(rows, cache):
    lines = []
    for i, r in enumerate(rows):
        item = dict(r, raw_title=re.sub(r"\s+", " ", r.get("raw_title") or "")[:RAW_MAX])
        raw = att.prompt_text(item, cache)
        lines.append(f"{i}|{r['matter_type']}|{r.get('requester', '')}|{raw}"
                     f"|{r['clean_title']}|{r['summary']}")
    return f"""Rewrite the title and description of each Cincinnati City Council item.
Return a JSON array, one object per item: {{"i":index,"t":"title","s":"description"}}
{up.STYLE_RULES}
Base the facts on the Legistar text; correct the current title or description where it disagrees.
Hard limits: t at most 12 words, s at most 30 words; longer answers are rejected. To fit, keep the action, the amount and the main place or organization and leave out the rest.
Items (index|type|requester|Legistar text|current title|current description):
{chr(10).join(lines)}
JSON array only, no markdown."""


def parse_items(raw):
    """Return the JSON array of item objects in the reply, ignoring any text around it.
    Tries each '[' in turn and keeps the first one that decodes to a list of objects
    with an "i" key."""
    dec = json.JSONDecoder()
    for k in [m.start() for m in re.finditer(r"\[", raw)]:
        try:
            data, _ = dec.raw_decode(raw[k:])
        except ValueError:
            continue
        if isinstance(data, list) and data and all(isinstance(d, dict) and "i" in d for d in data):
            return data
    raise ValueError("no JSON item array in reply: " + raw[:80].replace("\n", " "))


def ask(client, model, prompt):
    resp = client.messages.create(model=model, max_tokens=4000,
                                  messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "max_tokens":
        raise ValueError("response cut off at max_tokens")
    return parse_items(resp.content[0].text), resp.usage.input_tokens, resp.usage.output_tokens


def call(client, model, rows, cache):
    return ask(client, model, prompt_for(rows, cache))


def shorten_prompt(pairs):
    """pairs: [(index, title, description)] that came back over the word limits."""
    lines = "\n".join(f"{i}|{t}|{s}" for i, t, s in pairs)
    return f"""Shorten each title to at most 12 words and each description to at most 30 words.
Keep the facts, names and amounts that matter most; drop the rest. Keep the same style:
articles where prose needs them, no comma before the final "and", numbers as figures,
titles with no ending period, descriptions as one sentence ending with a period.
Return a JSON array, one object per item: {{"i":index,"t":"title","s":"description"}}
Items (index|title|description):
{lines}
JSON array only, no markdown."""


def clean(d):
    t = (d.get("t") or "").strip().rstrip(".").strip()   # titles take no ending period
    s = (d.get("s") or "").strip()
    return t, s


def usable(t, s):
    """Reject output that breaks the rules badly enough to keep the old text."""
    if not t or not s:
        return "empty"
    if re.search(r"[{}\[\]]", t + " " + s):
        return "stray bracket"
    if len(t.split()) > TITLE_MAX:
        return "title too long"
    if len(s.split()) > DESC_MAX:
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
    ap.add_argument("--model", choices=sorted(MODELS), default="sonnet-5-5")
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

    # Items whose Legistar title stops short get their attachment text first.
    cache = att.load_cache()
    stubs = [r for r in todo if att.needs_attachment(r.get("raw_title", ""))]
    if stubs:
        print(f"{len(stubs)} rows need attachment text; fetching any not cached.")
        att.ensure_text(stubs, cache, up.API_BASE, limit=len(stubs))
        if not a.dry_run:
            att.save_cache(cache)

    model, in_rate, out_rate = MODELS[a.model]
    client = anthropic.Anthropic(api_key=up.ANTHROPIC_API_KEY)
    tin = tout = 0
    done, kept, pairs = 0, [], []
    for b in range(0, len(todo), BATCH):
        chunk = todo[b:b + BATCH]
        try:
            data, i_t, o_t = call(client, model, chunk, cache)
            tin, tout = tin + i_t, tout + o_t
        except Exception as e:
            print(f"  batch {b // BATCH + 1}: error ({e}); rows left unchanged")
            kept += [(r["file_number"], f"batch error: {str(e)[:60]}") for r in chunk]
            continue
        got = {d.get("i"): clean(d) for d in data}
        # One shortening pass for answers over the word limits.
        long_ = [(i, *got[i]) for i in got if usable(*got[i]) in ("title too long", "description too long")]
        if long_:
            try:
                data2, i_t, o_t = ask(client, model, shorten_prompt(long_))
                tin, tout = tin + i_t, tout + o_t
                for d in data2:
                    if d.get("i") in got:
                        got[d["i"]] = clean(d)
            except Exception as e:
                print(f"  batch {b // BATCH + 1}: shortening error ({e})")
        for i, r in enumerate(chunk):
            t, s = got.get(i, ("", ""))
            why = usable(t, s)
            if why:
                kept.append((r["file_number"], why))
                continue
            pairs.append((r["file_number"], r["matter_type"], r["clean_title"], t, r["summary"], s))
            if not a.dry_run:
                r["clean_title"], r["summary"] = t, s
                if REWRITE_MARK not in (r.get("notes") or ""):
                    r["notes"] = ((r.get("notes") or "") + " " + REWRITE_MARK).strip()
            done += 1
        cost = tin / 1e6 * in_rate + tout / 1e6 * out_rate
        print(f"  batch {b // BATCH + 1}: {done} rewritten so far, ${cost:.3f}")

    cost = tin / 1e6 * in_rate + tout / 1e6 * out_rate
    per = cost / len(todo) if todo else 0
    eligible_left = sum(1 for r in rows if eligible(r))
    summary = [f"## Title and description rewrite, {a.model}{' (dry run, nothing saved)' if a.dry_run else ''}",
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
