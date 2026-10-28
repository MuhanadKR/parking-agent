# Chunking review

## Bullet regression

`test_bullets_that_fit_are_not_split_between_chunks` uses eight list items,
each small enough to fit individually, with a 180-character prefixed cap.
It requires every original bullet to appear intact in exactly one chunk.

Before the fix (`python -m pytest -q tests/test_chunking.py -k bullets`):

```text
assert sum(bullet in c.body for c in chunks) == 1
E assert 0 == 1
1 failed, 3 deselected in 0.22s
```

After the fix (`python -m pytest -q`):

```text
5 passed in 2.80s
```

The splitter now recognizes bullet and numbered-list boundaries. Items that
individually exceed the available body capacity still split at whitespace;
tables remain atomic and explicitly marked oversized if necessary.

## Corpus report

Default cap: 1,200 characters including prefix, not tokens. No API calls.

| File | Chunks | Minimum | Average | Maximum | Oversized |
|---|---:|---:|---:|---:|---:|
| 01-lot-information.md | 6 | 264 | 414.3 | 653 | 0 |
| 02-pricing-and-rates.md | 8 | 213 | 334.2 | 630 | 0 |
| 03-permits.md | 6 | 236 | 449.3 | 925 | 0 |
| 04-enforcement-and-fines.md | 8 | 203 | 350.1 | 750 | 0 |
| 05-accessible-and-ev-parking.md | 9 | 231 | 349.3 | 508 | 0 |
| 06-lost-tickets-refunds-and-disputes.md | 6 | 232 | 482.7 | 698 | 0 |
| Overall | 43 | 203 | 388.3 | 925 | 0 |

Short means body < 200 characters, excluding prefix. This is a review flag,
not a minimum-size requirement. Numbers below are display indices, not IDs.

| Index | File | Section | Body chars | Total chars |
|---|---|---|---:|---:|
| 1 | 01 | Introduction | 168 | 264 |
| 5 | 01 | Accepted payment methods | 158 | 266 |
| 6 | 01 | Contact us | 185 | 279 |
| 7 | 02 | Introduction | 113 | 213 |
| 9 | 02 | How time is billed | 123 | 229 |
| 12 | 02 | Permit holders | 160 | 262 |
| 13 | 02 | Discounts | 144 | 241 |
| 18 | 03 | Visitor Day Pass | 152 | 236 |
| 19 | 03 | How to apply | 182 | 262 |
| 21 | 04 | Introduction | 115 | 223 |
| 24 | 04 | Overstay allowance | 144 | 258 |
| 25 | 04 | Fine notices | 96 | 204 |
| 26 | 04 | Paying a fine | 169 | 278 |
| 28 | 04 | Appeals | 100 | 203 |
| 29 | 05 | Introduction | 101 | 231 |
| 30 | 05 | Accessible parking > Where the spaces are | 169 | 328 |
| 34 | 05 | Electric vehicle charging > Starting a session | 152 | 316 |
| 36 | 05 | Electric vehicle charging > Rules | 116 | 267 |
| 37 | 05 | Electric vehicle charging > Faulty chargers | 139 | 300 |
| 38 | 06 | Introduction | 99 | 232 |

## Chunk-ID decision for ingestion

Use SHA-256 over a canonical JSON array of chunker version, corpus-relative
source path, title, section path and body. This is deterministic across runs
and avoids renumbering unrelated chunks when another section is inserted.
Identical chunks in the same section intentionally deduplicate. Changed text
gets a new ID; ingestion must remove superseded IDs for that source in a
transaction. Store embedding model and dimension separately: a model change
requires re-embedding even if the content ID stays the same. IDs are a design
decision here, not implemented in the chunker yet.

## Design answers (inferred; original two questions were not provided)

1. **Why section-aware boundaries and no overlap?** These policies have short,
   titled rules. Keeping section context avoids mixing unrelated rules; no
   overlap avoids duplicate retrieval hits and repeated embedding cost.
   Very long items can still lose context when split. Evaluate that limitation
   before introducing overlap. Keep short standalone rules intact rather than
   merging unrelated sections just to reach a length target.
2. **Why repeat context in every prefix?** Retrieval returns isolated chunks.
   The document title and nested heading path clarify which policy the text
   belongs to; the source supports attribution. The prefix costs tokens and
   counts toward the cap, but the body remains separately available.

Concrete prefix (followed by a blank line and the chunk body):

```text
Source: 05-accessible-and-ev-parking.md
Title: Harborline Parking: Accessible and Electric Vehicle Parking
Section: Electric vehicle charging > Charging fees
```
