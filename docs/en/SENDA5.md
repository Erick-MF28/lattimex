# SENDA5: current version and audited results

*[Español](../SENDA5.md)*

Version 1.3.0 integrates **SENDA5 with the corrected clock**, engine `lattimex-engine-1.9.0`.
It is the candidate measured on November 15, 2026: local search on reinserted customers every three
iterations, and route elimination for a free fleet when the initial solution averages fewer than
seven customers per route. Initial polishing counts against the budget; final polishing reserves
at most 0.5 s and returns unused time to the search. Parameters are fixed in the source.
SENDA4 is an experimental predecessor; SENDA5 is the integrated core.

## Latest evidence: four seconds

100 X instances, 100–1,000 customers, CVRP without time windows, free fleet, one thread, one run
per tool and instance: 700 trials. Timing starts before reading the instance and ends when routes
are available. It includes external processes/JVM, excludes Python startup and library imports.
Per-tool, per-instance calibration subtracts measured overhead and a 0.02 s margin from the limit.
SENDA5 uses SENDA2 below 125 nodes including the depot.

**SENDA5 has a lower gap than FILO2, HGS, PyVRP, OR-Tools and nearest neighbor. No significant
difference is detected against AILS-II.** The contract's word “tie” does not establish equivalence.
These findings apply to this sample and configuration, with one run per instance.

The main column recalculates the original costs against [CVRPLIB bounds retrieved on November 17, 2026](https://galgos.inf.puc-rio.br/cvrplib/en/instances).
These are updated references, not new runs. Original contract values remain alongside them.

| Tool | Mean gap, current BKS (%) | Mean gap, contract (%) | No solution / 100 |
|---|---:|---:|---:|
| **SENDA5** | **0.534** | **0.531** | **0** |
| AILS-II | 0.581 | 0.578 | 0 |
| FILO2 | 0.707 | 0.704 | 0 |
| HGS | 1.694 | 1.691 | 2 |
| PyVRP | 2.210 | 2.207 | 0 |
| OR-Tools | 7.810 | 7.806 | 0 |
| Nearest neighbor | 25.105 | 25.102 | 0 |

**Both columns average the 98 instances solved by all seven tools.** HGS returned no solution for
X-n670-k130 or X-n936-k151. Across its own 100 solutions, SENDA5's mean gap is **0.549 %** with
current bounds (0.547 % with frozen bounds); AILS-II's is 0.593 % (0.590 %). Do not describe 0.534 %
as an average over 100 instances.

| SENDA5 − rival (current BKS) | Paired n | Difference (pp) | Bootstrap 95% CI (pp) | Win / tie / loss |
|---|---:|---:|---|---|
| AILS-II | 100 | −0.043 | [−0.117, +0.024] | 54 / 3 / 43 |
| FILO2 | 100 | −0.187 | [−0.263, −0.114] | 63 / 3 / 34 |
| HGS | 98 | −1.161 | [−1.407, −0.925] | 76 / 5 / 17 |
| PyVRP | 100 | −1.746 | [−1.966, −1.536] | 95 / 3 / 2 |
| OR-Tools | 100 | −7.548 | [−8.431, −6.722] | 100 / 0 / 0 |
| Nearest neighbor | 100 | −24.927 | [−27.797, −22.179] | 100 / 0 / 0 |

Pairs include every instance solved by both tools, so differences do not always equal subtraction
of the first table's means. Percentile bootstrap: 10,000 instance resamples, seed 12345, indices
249 and 9749; no multiple-comparison correction. Twelve updated bounds leave conclusions unchanged.
Full figures and source hashes are in [the audit summary](../senda5_auditoria.json).

Both predefined median-time conditions pass: SENDA5 3.980 s; other timed arms 3.974–3.980 s.
**This is not a hard 4.000 s deadline:** SENDA5's maximum was 4.124 s, with one trial above 4.10 s.
Nearest neighbor finishes early. The speed sentinel's median ratio was 1.001.

## Historical SENDA4 and SENDA5 evidence

SENDA4's contract contains 9,600 trials (100 X, six arms, 0.5–4 s, two repetitions). Its primary
comparison against SENDA3 on 68 instances unused in SENDA4 development is −0.128 pp at 4 s,
95% CI [−0.186, −0.072]. SENDA5's earlier contract contains 9,000 trials (100 X, three arms,
0.5–5 s, three repetitions): SENDA5 − SENDA4 is −0.033 pp [−0.067, −0.002] at 4 s;
short routes improve by −0.119 pp.

These pass their original rules but used nominal optimizer limits without matching wall time.
In the second contract, nominal 4 s yielded median measured times of 4.055 s for SENDA4/SENDA5
and 4.253 s for AILS-II; SENDA5 reached 4.543 s. Leadership across those budgets cannot be
transferred to the corrected-clock version. All SENDA5 short-route instances had been seen before.

The later corrected-clock exploration has 16 X instances and 384 trials. At 10 s, SENDA5 − AILS-II
is +0.089 pp [−0.041, +0.215]; intervals also cross zero at 30 and 60 s. At 120 s it is +0.107 pp
[+0.013, +0.203], with one repetition. This supports an exploratory disadvantage at 120 s,
**not a claim that AILS-II wins at every budget from 10 s onward**. The e-means and 3,000–10,000
customer experiments are not release evidence: they were exploratory, with one seed and references
not verified in their original report.

## Audit scope and limitations

The November 17 audit covers 19,300 contracted trials plus 384 corrected-clock trials. It checks
contract/dependency hashes, complete cells and seeds, duplicates, cost-to-gap arithmetic, means,
236 bootstrap comparisons and sentinels. Frozen contracts remain unchanged. The old local witness
for X-n384-k52 costs 65,940; the downloaded and independently checked official solution costs
65,928, matching the frozen reference.

- Historical logs contain costs, route counts and `verified`, **not the routes themselves**.
  Arithmetic and integrity can be checked; historical route feasibility cannot be independently
  revalidated from those logs. Integration tests retain their own newly computed routes.
- One run per instance in the principal comparison; intervals capture between-instance variation.
  AILS-II did not receive the harness seed. Development used these instances.
- The public contract's PyVRP version is blank and its package and OR-Tools dependencies are not
  frozen. P2's saved JSON covers only one of its two conditions; this audit checks both.
- No people or Excel were measured. Nearest neighbor is not an estimate of an expert's performance;
  historical figures labelling it that way do not support a comparison with people.
- CVRP results do not establish improvements for time windows, 3D loading, fixed fleets or road
  networks. Product tests check integration and feasibility, not competitive performance.

## Integration

```bash
python -m lattimex build
python -m lattimex cvrp X-n1001-k43.vrp --time 4 --router senda5
python -m unittest tests.test_senda5 tests.test_senda3 -v
```

The CLI defaults to SENDA5; `--router senda3`, `senda2` and `senda` still select their historical
libraries. The CLI assigns 80% of `--time` to the core: **`--time 4` does not exactly reproduce
the calibrated four-second experiment above**.

The full engine loads `libsenda5` through `LATTIMEX_CORE5`, preserving the policy of SENDA 1.0
for `router=auto` with fewer than six destinations per vehicle. In the API, `senda5`, `senda3` and
`senda2` remain aliases for the current loaded core; `senda` forces the old one. Responses identify
the selected core. Parallel portfolio runs now include initial polishing in each run's budget;
the extra 12% discount is removed for SENDA5. This product extension is tested separately and is
not presented as a newly confirmed benchmark.
