# Paper Plan — Automated 3D FPGA Architecture Search

Rough sketch for discussion. Results are placeholders (XX) until the campaign runs. The point of
this doc is to lock the *narrative* and figure out what we still need to measure.

---

## 1. Thesis in one paragraph

3D FPGAs promise shorter wires and lower delay, but stacking multiplies the architecture design
space: for every layer you must decide where the hard-block columns sit and how much vertical
routing to pay for. Prior work, including Lay of the Layers, evaluates a small number of
hand-chosen configurations, because each evaluation is a full synthesis, pack, place and route
run (10-20 minutes) and because building a valid 3D architecture plus its routing resource graph
by hand is slow. We remove both bottlenecks with a programmatic architecture generator and a
parallel multi-objective optimizer on top of LaZagna, then use it to ask whether automated search
finds layer layouts that beat the obvious uniform baseline, and whether the best layout depends on
the workload.

## 2. Narrative in five beats

1. **Promise.** 3D stacking shortens critical paths and wirelength on FPGAs.
2. **Problem.** The design space explodes with layers. On the 36x36 grid we use, per-column
   placement alone is 3^68, about 3e32 configurations, before you add interlayer connectivity,
   connection pattern and interlayer delay. Nobody searches this.
3. **Why nobody searches it.** One point in the space costs a full VTR flow, so brute force is
   out, and hand-writing 3D architecture XML plus custom RR graphs does not scale.
4. **What we do.** A Python architecture model that emits valid VTR XML for arbitrary column
   layouts, a multi-objective Bayesian search over the space (critical path delay and wirelength),
   and a containerized SLURM campaign that evaluates 16 architectures at once so a real search
   finishes in hours instead of days.
5. **What we find (the hoped-for punch).** Automated search beats the uniform aligned 3D baseline
   by XX% CPD and XX% wirelength, and **the best layout differs per benchmark**, which argues that
   3D hard-block placement should be searched per application rather than fixed once. That last
   point is the paper's reason to exist, and it is also the strongest argument for the tool.

If the workload-specificity result does not hold, the fallback story is still publishable as a
framework and characterization paper: here is the first automated search over 3D FPGA layer
layouts, here is how much headroom exists over the natural baseline, and here is how to budget
compute for it.

## 3. Research questions

- **RQ1 (calibration).** How much does 2-layer stacking actually buy on hard-block-heavy ML
  workloads, measured against a *true* 1-layer 2D baseline at the channel width each architecture
  needs rather than a shared optimistic width?
- **RQ2 (the main claim).** Does optimizing per-column DSP and BRAM placement across layers beat
  the aligned uniform reference, and by how much on CPD and wirelength?
- **RQ3 (methodology).** Which search strategy is most sample-efficient for this space, TPE versus
  NSGA-II versus random? Practical guidance matters when one sample costs 10-20 minutes.
- **RQ4 (generality).** Does the best layout transfer across benchmarks, or is it workload
  specific? Motivates per-application search if it is specific.
- **RQ5 (sensitivity, optional).** How do interlayer connectivity percentage and interlayer delay
  ratio trade against layout choices? Tells us which knob deserves the search budget.

## 4. Section outline

**1. Introduction** (1 page)
Stacking promise, space explosion, cost per evaluation, our two contributions (generator plus
parallel optimizer), headline numbers, contribution bullets.

**2. Background and related work** (1 page)
3D FPGA architectures and integration styles. VTR and OpenFPGA flow. LaZagna and what it already
does (3D switch block generation, custom RR graphs). Design space exploration and Bayesian
optimization in EDA, and why expensive-evaluation methods apply here. Where we differ from prior
3D FPGA studies: they compare configurations, we search over them.

**3. Search space and problem formulation** (1 to 1.5 pages)
Formal space: per-layer per-column block type, interlayer connectivity fraction, connection
pattern, interlayer delay ratio, switch block style. Size of the space. Objectives: geometric mean
CPD and total wirelength across seeds, normalized against a reference architecture so numbers are
comparable across benchmarks. Constraints that keep samples physically sensible (CLB-majority
block ratios). Why multi-objective rather than a weighted scalar.

**4. Framework** (1.5 pages)
Architecture generator: Python object model to VTR XML, content-hashed so distinct layouts never
share a cached RR graph (this was a real bug worth one sentence). Optimizer loop and how a trial
maps to a full flow invocation. Reference baseline and normalization. Parallel evaluation: shared
journal-backed study, N independent SLURM workers pulling one trial at a time, constant-liar TPE
so concurrent workers do not collapse onto the same point. Reproducibility: single container
image, one-command campaign. **Figure 1** goes here (flow diagram), **Figure 2** here (search
space illustration).

**5. Experimental setup** (0.75 page)
Benchmarks and why: clma from MCNC as a soft-logic control that reproduces prior results, and
eltwise, conv_layer and lstm from Koios because hard-block placement only matters if the workload
uses hard blocks. Architecture templates (dsp_bram family), grids and channel widths, 3 seeds
everywhere with geometric mean, cluster and per-trial resources. Verification gate: a result
counts only if VPR reports success with real CPD and wirelength, which kills silent
half-failures. **Table 1** here (benchmark characteristics).

**6. Results** (2.5 pages)
- 6.1 RQ1, 3D versus true 2D. **Table 2**.
- 6.2 RQ2, searched versus reference layout. **Table 3** plus **Figure 3** (CPD versus wirelength
  Pareto front with the reference marked).
- 6.3 RQ3, sampler efficiency. **Figure 4** (best-so-far versus trial count per sampler).
- 6.4 RQ4, cross-benchmark comparison of the best layouts. **Figure 5** (winning column layouts
  side by side, this is the money figure if layouts differ).
- 6.5 RQ5, sensitivity. **Table 4**.

**7. Discussion and limitations** (0.5 page)
Two layers only, which is what LaZagna's switch block generation supports today. Interlayer delay
is a swept parameter rather than an extracted number from a real stacking process, so results are
reported as a function of it. Search budget is tiny relative to the space, so we claim
improvements found, not optimality. Small benchmark count. Seed noise, hence 3 seeds and geomean.

**8. Conclusion** (0.25 page)
Search beats hand-picked layouts, the answer is workload dependent, tool and container are
released.

## 5. Figure and table manifest

| Item | Content | Status |
|---|---|---|
| Fig 1 | Framework flow: generator, optimizer, parallel workers, VTR | can draw now |
| Fig 2 | Search space: column assignments over 2 layers | can draw now |
| Fig 3 | Pareto front, CPD versus WL, reference point marked | needs campaign |
| Fig 4 | Convergence per sampler, best-so-far versus trials | needs campaign |
| Fig 5 | Best layouts per benchmark, side by side | needs campaign |
| Table 1 | Benchmark characteristics: LUTs, DSPs, BRAMs, grid, cw | mostly have |
| Table 2 | 3D versus true 2D per benchmark | needs campaign |
| Table 3 | Searched versus reference layout, CPD and WL, percent | needs campaign |
| Table 4 | Sensitivity to connectivity and delay ratio | needs campaign |

## 6. What we can claim today versus what needs the run

| Claim | Status |
|---|---|
| Framework exists, generates valid 3D architectures, runs end to end | done, verified |
| Reproduces prior clma result (+8.86% CPD) | done, this is our sanity anchor |
| Koios hard-block benchmarks reach VPR at all | done, this was a blocker we fixed |
| Parallel search infrastructure works and scales | infrastructure verified locally, cluster scaling pending |
| 3D versus true 2D percentages | pending |
| Searched layout beats reference | pending |
| Sampler ranking | pending, and the laptop numbers were contaminated by resource contention so the cluster run is the real first measurement |
| Layout is workload specific | pending, this is the one I most want to see |

## 7. Open questions for Ismael

1. **Resource matching in the search.** This is the one I actually want your read on. Each column
   is sampled independently against CLB-majority fractions, so the *expected* block counts line up
   with the reference almost exactly (sampled 23.1 CLB, 3.4 DSP, 7.5 BRAM against a reference of
   23, 4, 7 out of 34 interior columns), but the *per-trial* counts swing a lot. Over 20k
   simulated draws, BRAM columns land between 4 and 12 and DSP columns between 1 and 6 for the
   middle 90% of trials. So a trial can have six times the DSP columns of another trial, on
   benchmarks where DSP is the block that matters. A reviewer will reasonably ask whether an
   improvement came from a better arrangement or just from more hard blocks. Two ways out: report
   block counts alongside every trial and condition on them, or permute a fixed multiset of
   columns so every trial has identical resources and only the arrangement varies. I lean toward
   the fixed multiset because it turns RQ2 into a clean placement claim, and the space stays far
   larger than any budget we could spend (about 9e10 arrangements per layer, so roughly 9e21 over
   two layers, versus 3e32 for the current unconstrained version). I did not change it yet because
   it changes what the pending run measures and that felt like your call.
2. **Search budget.** 35 trials against a space this size is a drop. Is the honest framing
   "improvements found within a fixed budget" plus the sampler study, or do we want a much larger
   run on one benchmark to show the curve flattening?
3. **Venue and timing.** I do not want to assume deadlines. What are we targeting, and does this
   land as a full paper, a short paper, or part of a larger journal version of Lay of the Layers?
4. **Scope of my part.** Happy to own the framework, setup and results sections and all the
   figures, and to draft the rest for you to reshape.

## 8. Rough ordering of work

1. Now, during PACE downtime: Figures 1 and 2, Table 1, related work reading, and the
   resource-matching decision from question 1.
2. When PACE is back: the campaign, then Tables 2 and 3 and Figures 3 and 4.
3. Then: cross-benchmark run for RQ4 and Figure 5, which is the one that decides how strong the
   story is.
4. Then: sensitivity sweep for RQ5 if there is room, and full draft.
