---
name: heap-report
description: How to write a heap-dump report for an application's developers from analysis evidence — sizes, counts, dates and code citations formatted for people, and the order a reader needs. Use when writing a summary, takeaways or report from heap-dump evidence.
---

# Writing a heap report

The evidence decides WHAT the report says. This skill only decides HOW it reads. Never add a claim,
a cause or a recommendation that is not in the evidence you were given.

## Order

1. The one thing that matters most: what dominates the heap, and how much of it.
2. What is wrong, largest first — each with its figure.
3. Where in the code it comes from — the class, field and line the evidence names.
4. What to change, tied to those lines.
5. What is fine — briefly, only where the evidence shows it (e.g. no finalization backlog).

Plain prose, one paragraph unless asked otherwise. No headings, no bullet lists, no preamble such as
"The heap analysis reveals".

## Numbers

- **Sizes:** never raw byte counts. Use binary units with one decimal, and choose the unit that gives
  a figure between 1 and 1023: `107.6 MB`, `4.5 MB`, `233.0 KB`, `1.2 GB`. (1 KB = 1024 bytes.)
- **Proportions:** give a share when the evidence has both parts: `107.6 MB, 80% of the heap`.
- **Counts:** with thousands separators: `2,238 instances`, `516,810 objects`.
- Round once, at the end; never print a figure with more than three significant digits after the
  conversion. Quote the evidence's own rounding where it gives one.

## Dates and times

- A timestamp in the evidence is already an ISO date-time. Write it for a person:
  `21 Oct 2026, 14:03 UTC` — day, short month, year, 24-hour time, zone.
- Durations: `9.6 s`, `3 min 12 s`, `1 h 05 min` — never raw milliseconds.
- Omit a date the evidence does not give; never write an epoch number.

## Citing code

- A class by its simple name, the package only when two share a name: `PrimitiveLongMap`, `ClassTable`.
- A field as `Owner.field` in backticks: `` `ClassTable.supers` ``. A nested owner keeps its `$`:
  `` `ClassCensus$Tally.references` ``.
- A source line as `File.java:123`, or `File.java:200–201` for a range; quote the code itself in
  backticks when it is short: `` `new PrimitiveLongMap(1024)` ``.
- JVM options in backticks: `` `-XX:G1HeapRegionSize` ``.

## Words

- Say "retains" for retained bytes and "holds" for references; never "uses".
- No hedging stack ("might potentially") and no praise padding ("well-designed"), unless the evidence
  itself says something is done right — then say what, in a clause.
- About 200 words when asked for a summary.
