#!/usr/bin/env python3
"""
Build a Moore item-code -> description map.

Seeds from the QB report's `Item` column (authoritative: "<code> (<desc>)"),
then harvests descriptions from invoice PDFs. Each invoice page lists item
codes and a concatenated PRODUCT DESCRIPTION blob in the same order. Using the
known descriptions as a vocabulary, the blob is greedily segmented; when the
number of segments equals the number of item codes on the page, the alignment
is trusted and any new code->description pairs are learned. Repeated until no
new descriptions are learned (so invoice-only items get named too).

Usage:
    python3 scripts/build_item_descriptions.py QB.csv RAWDIR out.json
"""
from __future__ import annotations
import csv, glob, json, re, sys


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def seed_from_qb(path):
    m = {}
    with open(path) as f:
        r = csv.reader(f); next(r)
        for row in r:
            if len(row) < 5 or not row[2].strip():
                continue
            item = row[4]
            code = item.split()[0] if item else ""
            mm = re.match(r"\s*\S+\s*\((.*?)\)?\s*$", item)
            if code and mm:
                m[code] = norm(mm.group(1)).rstrip(".").strip()
    return m


def pages(rawdir):
    for f in sorted(glob.glob(rawdir + "/*.txt")):
        n = norm(open(f).read())
        for m in re.finditer(
            r"ITEM NUMBER (.*?) PRODUCT DESCRIPTION (.*?) QTY ORDERED", n
        ):
            items = m.group(1).split()
            blob = re.sub(r"\*\* .*? \*\*", " ", m.group(2))
            blob = norm(blob)
            yield items, blob


def segment(blob, vocab_sorted):
    """Greedy longest-prefix segmentation, merging consecutive unknown tokens
    into a single unknown run. Returns list of (text, matched?)."""
    segs = []
    pos = 0
    bl = blob
    pending = []  # accumulate unknown tokens
    def flush():
        if pending:
            segs.append((" ".join(pending), False))
            pending.clear()
    while pos < len(bl):
        best = None
        for v in vocab_sorted:
            if v and bl.startswith(v, pos):
                best = v
                break
        if best:
            flush()
            segs.append((best, True))
            pos += len(best)
            while pos < len(bl) and bl[pos] == " ":
                pos += 1
        else:
            nxt = bl.find(" ", pos)
            if nxt < 0:
                pending.append(bl[pos:]); pos = len(bl); break
            pending.append(bl[pos:nxt])
            pos = nxt + 1
    flush()
    return segs


def main():
    qb, rawdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
    desc = seed_from_qb(qb)
    page_list = list(pages(rawdir))
    for _ in range(4):
        vocab = sorted(set(desc.values()), key=len, reverse=True)
        learned = 0
        for items, blob in page_list:
            if len(items) == 1 and items[0] not in desc and blob:
                desc[items[0]] = blob; learned += 1; continue
            segs = segment(blob, vocab)
            # trust alignment only when total segment count == item count
            if len(segs) == len(items):
                for code, (d, ok) in zip(items, segs):
                    if code not in desc:
                        desc[code] = d; learned += 1
        if not learned:
            break
    json.dump(desc, open(out, "w"), indent=0)
    print(f"item descriptions: {len(desc)}")


if __name__ == "__main__":
    main()
