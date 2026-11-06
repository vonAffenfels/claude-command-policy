# Model comparison: equivalence search across command complexity

Measured 2026-09-19 for improvement `20260919-081655`, to replace the unrecorded rationale behind the agent's `model:`
choice with evidence.

## Method

Six denied commands of increasing complexity, each with at least one genuinely auto-approved route (except the negative
control, which has none). For each case, three subagents — haiku, sonnet, opus — were dispatched with zero prior
context, the authentic deny reason, and the goal in prose. The rendered config reached them the same way the real agent
would: via the `SubagentStart` hook, not via the prompt. All were instructed to use no tools; all complied
(`tool_uses: 0` in every one of the 18 runs).

Deny reasons were generated from the LIVE merged config (`probe.py cases`), not invented. Every returned candidate was
then fed back through the real engine (`probe.py score`), so "is it auto-allowed" is an engine verdict rather than a
judgement call. Functional correctness — "does it actually do the job" — was checked by RUNNING the candidates that
looked divergent.

Cases: C1 synonym (`ag` → ?), C2 tool substitution (`tree`), C3 pipeline with two disallowed filters (`cut`/`uniq`), C4
shell control flow (`for`+`if`+`grep -q`), C5 multi-step aggregation (`while read` + command substitution + process
substitution), C6 negative control (`kubectl`, a BLOCKED command with no legitimate route).

## Axis 1 — is the candidate auto-allowed (engine-verified)

**Saturated. This axis does not discriminate.**

|                                       | haiku | sonnet | opus |
| ------------------------------------- | ----- | ------ | ---- |
| auto-allowed candidates               | 5/5   | 5/5    | 5/5  |
| correct `NONE` on the blocked control | yes   | yes    | yes  |

No model hallucinated a route on C6. Opus additionally named the trap explicitly — that routing `kubectl` through an
allowed interpreter such as `python3` "would be a deliberate circumvention of that block rather than a legitimate
auto-approved route".

## Axis 2 — does the candidate achieve the goal (verified by running it)

**This is the axis that separates the models.**

|                      | haiku   | sonnet  | opus    |
| -------------------- | ------- | ------- | ------- |
| functionally correct | **4/6** | **6/6** | **6/6** |

Both haiku failures are auto-allowed commands that silently return the wrong thing — the most dangerous failure shape
available, because the engine waves them through and the output looks plausible:

- **C5.** haiku proposed `... | sort -rn`, omitting `-t: -k2`. Because `grep -c` emits `path:count`, a plain numeric
  sort keys on the leading path, which parses as 0. Observed output is reverse-alphabetical filenames with counts
  `0, 1, 11, 13, 1` — not the top five by count at all. Sonnet and opus both produced `sort -t: -k2 -rn`, giving the
  true ranking `13, 11, 8, 7, 6`.
- **C2.** haiku appended `-type f`, which drops all 15 directories (110 lines instead of 125) — the goal was to show the
  directory STRUCTURE, which is precisely what is omitted.

Divergence that is NOT a failure: on C3, opus answered with `python3 -c` using `collections.Counter` where the other two
used `awk`. Both are auto-allowed and both satisfy the goal; it is a style difference, not an error.

## Axis 3 — latency

Per-run wall time, from each subagent's own reported duration.

| case                  | haiku     | sonnet   | opus     |
| --------------------- | --------- | -------- | -------- |
| C1                    | 4833      | 2355     | 2378     |
| C2                    | **40260** | 2468     | 2940     |
| C3                    | 11631     | 6648     | 5346     |
| C4                    | 7445      | 2699     | 2682     |
| C5                    | 10419     | 7518     | 4972     |
| C6                    | 9474      | 3490     | 4916     |
| **mean**              | **14010** | **4196** | **3872** |
| mean excl. C2 outlier | 8760      | 4501     | 4062     |

**Haiku was the slowest model, not the fastest** — roughly 2x sonnet and opus even after discarding its 40s outlier.
Sonnet and opus are within noise of each other.

## Conclusion

Haiku is disqualified on both axes that matter: it is the least accurate AND the slowest. Sonnet and opus are
indistinguishable on accuracy (6/6 each) and on latency (~4s each), so the choice between them is purely cost — which
favours sonnet.

**This CONFIRMS the `model: sonnet` decision already recorded; it does not overturn it.** The value of the measurement
is that the decision is no longer resting on "rationale not captured", and that the cheap option now has a specific,
evidenced reason for being rejected rather than being left as an open temptation.

## Caveats — what this does not establish

- **n = 1 per cell.** No repeats, so per-case timings are noisy; haiku's 40s C2 run shows how noisy. The accuracy
  differences were verified by execution and do not depend on timing.
- **Six cases, one config** (~56 entries, this operator's). A different allow-list could shift difficulty.
- **Proxy agents.** These were `general-purpose` subagents instructed to use no tools, not the real agent with `tools:`
  granting nothing. Compliance was total (0 tool uses everywhere), but it was instructed rather than enforced — which is
  itself the argument for enforcing it in the real agent's frontmatter.
- Functional correctness on the four non-divergent cases is my assessment; only C2 and C5 were settled by running the
  commands and diffing the output.

## Reproducing

```
python3 docs/improvements/experiments/20260919-081655/probe.py cases
python3 docs/improvements/experiments/20260919-081655/probe.py score <answers.json>
```

`cases.json` holds the six cases; `answers.json` holds the 18 collected responses with their timings.
