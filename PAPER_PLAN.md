# Paper Plan — Python-Native 3D FPGA Architecture Exploration

Rough sketch for discussion. Results marked XX are pending the campaign. The point of this doc is
to lock the narrative and surface what still needs deciding.

---

## 1. The narrative, in one paragraph

Specifying a 3D FPGA architecture today means hand-writing VTR architecture XML plus a matching
routing resource graph. That barrier is why 3D FPGA design space exploration has been carried out
over a handful of hand-designed points: Lay of the Layers characterizes **seven** layouts, and
seven is about what is reasonable to build by hand. The space those seven sit in is enormous. On
the 36x36 grid we use, per-column block placement alone is 3^68, roughly 3e32 configurations,
before interlayer connectivity, connection pattern, or interlayer delay. We remove the barrier with
a Python architecture API that emits valid VTR XML for arbitrary layouts, attach a multi-objective
optimizer to it, and evaluate at cluster scale. Then we ask the question the barrier was
previously preventing: **is anything in that space better than the hand-designed points, and does
the answer depend on the workload?**

The single sentence version: *manual architecture specification was the bottleneck on 3D FPGA
exploration, and removing it changes what questions you can ask.*

That framing matters because it makes the API a first-class contribution rather than plumbing, and
it makes the search results the evidence that the API was worth building. The two halves argue for
each other instead of competing for space.

## 2. Two possible framings (want your call)

**(A) Tool-forward.** "A Python API for 3D FPGA architecture exploration." Contribution is the
abstraction and extensibility, with the optimizer study as the demonstration that it enables real
work. Fits a tool track or TRETS. Risk: tool papers without a strong result can read thin.

**(B) Study-forward.** "Automated search over 3D FPGA layer layouts." Contribution is the
findings, API is infrastructure. Risk: the underlying 3D characterization is already Lay of the
Layers, so we are competing with your own prior work unless the search finding is strong.

**My lean: (A) with the study as a full results section**, because the honest novelty is *the space
became searchable*, and because it does not overlap Lay of the Layers. If the workload-specificity
result lands strongly, we can pivot toward (B) late without restructuring much. Curious which you
think fits the venue better.

## 3. Research questions

- **RQ1 (validation).** Does the generated-architecture path reproduce known results? Anchor: the
  aligned layout on clma gives +8.86% CPD over 2D, inside the range Lay of the Layers reports for
  a large CLB-heavy design. This is a section-5 sanity check, not a contribution.
- **RQ2 (the claim).** On hard-block-heavy ML workloads, does searching per-column DSP and BRAM
  placement across layers beat the aligned reference, and by how much on CPD and wirelength?
  Benchmarks: eltwise, conv_layer, lstm. **This is the Koios question, not an MCNC question.**
- **RQ3 (methodology, your open question).** How should a large parallel budget be spent on
  expensive architecture evaluations? Two axes, sampler (TPE, NSGA-II, random) and **batch width**
  (1, 16, 100+). This matters because sequential Bayesian optimization earns its keep from
  feedback between trials, and at batch 100 there is almost no feedback left, so TPE should decay
  toward random somewhere on that curve. Finding where is useful and, as far as I can tell,
  unanswered for FPGA architecture search.
- **RQ4 (generality).** Do the best layouts differ across benchmarks? If yes, 3D hard-block
  placement should be searched per application rather than fixed once, which is the strongest thing
  this paper could say.
- **RQ5 (secondary, MCNC's actual job).** On soft-logic benchmarks that predate hard blocks, does
  interlayer connectivity configuration matter? Current answer from the 3-seed study is mostly no:
  best around +3.4% CPD, several slightly negative, largely inside seed noise. A clean negative
  result, and it is what justifies moving the layout study to Koios.

## 4. Section outline

**1. Introduction** (1 page)
The XML barrier, the size of the space it hides, the two contributions (API, parallel search),
headline numbers, contribution bullets.

**2. Background and related work** (1 page)
3D FPGA integration styles. VTR and OpenFPGA. LaZagna and what it already provides (3D switch
block generation, custom RR graph construction). **Lay of the Layers as the direct predecessor:
seven characterized layouts, and we generalize from characterizing points to searching the space.**
Bayesian optimization for expensive-evaluation design problems, and batch BO for parallel budgets.

**3. The architecture API** (1.5 pages)
Object model to VTR XML. Layout as a 3D grid, any layer any arrangement, lowered internally to
VTR layout directives. Complex block list as the extensibility surface, primitives with BLIF
models composed into parent blocks, with tiles and models auto-inferred from the pb_type graph
since those three XML blocks are intertwined, with explicit overrides for the cases where the same
logical block needs a different physical tile (this is the resolution of the infer-versus-specify
question from April: infer by default, override when the architecture demands it). Experiment options as a second class, then both
passed to one call that runs LaZagna and returns results. One paragraph on validation: generated
architectures pass VTR parsing and complete pack, place, route and timing. **Figure 1** (API to
VTR to LaZagna flow), **Listing 1** (10 lines of Python producing a 2-layer architecture, this
listing is the tool contribution made concrete).

**4. Search formulation and parallel evaluation** (1.25 pages)
Space: per-layer per-column block type, connectivity fraction, connection pattern, interlayer
delay ratio, switch block style, with size. Objectives: seed-geomean CPD and wirelength,
normalized against a reference architecture. Constraints keeping samples physically sensible.
Parallel evaluation: journal-backed shared study, N independent jobs pulling one trial at a time,
constant-liar TPE, per-trial RR graph cleanup. Reproducibility: one container, one command.
**Figure 2** (search space), **Figure 3** (parallel worker architecture).

**5. Experimental setup** (0.75 page)
Benchmark roles stated explicitly, because they are not interchangeable: **clma and MCNC for RQ1
validation, RQ3 methodology and RQ5 connectivity, since they predate hard blocks and cannot
exercise placement. Koios (eltwise 11 DSP / 116 BRAM / ~1330 CLB, conv_layer, lstm) for RQ2 and
RQ4.** Grids, channel widths, 3 seeds with geomean, cluster resources. Verification gate: a result
counts only if VPR reports success with real CPD and wirelength. **Table 1** (benchmarks).

**6. Results** (2.5 pages)
- 6.1 RQ1 validation and 3D versus true 2D on hard-block workloads. **Table 2**.
- 6.2 RQ2 searched versus reference layout. **Table 3**, **Figure 4** (Pareto front, reference marked).
- 6.3 RQ3 sampler by batch width. **Figure 5** (best-so-far versus evaluations, curves per sampler
  per batch width). The interesting axis is wall-clock versus sample efficiency.
- 6.4 RQ4 best layouts side by side per benchmark. **Figure 6**, the money figure if they differ.
- 6.5 RQ5 connectivity on MCNC, reported as the negative result it appears to be. **Table 4**.

**7. Discussion and limitations** (0.5 page)
Two layers, which is what the switch block generation supports today. Interlayer delay is a swept
parameter, not extracted from a stacking process, so results are reported as a function of it.
Search budget is tiny against the space, so the claim is improvements found, not optimality. Small
benchmark count. Seed noise is real and worth a sentence with evidence: our own single-seed clma
number was +12.20% and the 3-seed picture was materially less optimistic, which is a concrete
warning for anyone doing this kind of study.

**8. Conclusion** (0.25 page)

## 5. Figure and table manifest

| Item | Content | Status |
|---|---|---|
| Fig 1 | API to VTR to LaZagna flow | can draw now |
| Fig 2 | Search space, columns over 2 layers | can draw now |
| Fig 3 | Parallel worker / shared study architecture | can draw now |
| Listing 1 | Minimal Python producing a 2-layer arch | can write now |
| Fig 4 | Pareto front, CPD vs WL | needs campaign |
| Fig 5 | Convergence per sampler per batch width | needs campaign, needs batch sweep added |
| Fig 6 | Best layouts per benchmark | needs campaign |
| Table 1 | Benchmark characteristics | mostly have |
| Table 2 | 3D vs true 2D | needs campaign |
| Table 3 | Searched vs reference | needs campaign |
| Table 4 | MCNC connectivity | have 3-seed data, want a rerun on the cluster |

## 6. Status of every claim

| Claim | Status |
|---|---|
| Python API generates valid VTR XML, passes parsing, completes full flow | done, verified |
| Reproduces prior clma result, +8.86% CPD aligned vs 2D | done, single seed, our anchor |
| Koios hard-block designs reach VPR at all | done, this was a blocker we fixed |
| Parallel search infrastructure works | verified locally, cluster scaling pending |
| MCNC connectivity effects are within noise | have 3-seed evidence, want cluster rerun for the paper |
| Single-seed results are over-optimistic | done, and worth reporting as methodology |
| 3D vs true 2D on hard-block workloads | pending |
| Searched layout beats reference | pending, the main claim |
| Sampler by batch width | pending, needs the batch sweep built |
| Layouts are workload specific | pending, the one I most want to see |

## 7. Open questions for you

1. **Resource matching in the search.** The one I most want your read on before the rerun. Each
   column is sampled independently against CLB-majority fractions, so *expected* block counts match
   the reference nearly exactly (sampled 23.1 CLB / 3.4 DSP / 7.5 BRAM against a reference of 23 / 4
   / 7 out of 34 interior columns). But *per-trial* counts swing hard. Over 20k simulated draws the
   middle 90% of trials land at 4 to 12 BRAM columns and 1 to 6 DSP columns, so one trial can carry
   six times the DSP of another on benchmarks where DSP is the block that matters. A reviewer will
   ask whether a win came from arrangement or from more hard blocks. Options: report counts per
   trial and condition on them, or permute a fixed multiset so every trial has identical resources
   and only arrangement varies. I lean fixed multiset, since it makes RQ2 a clean placement claim
   and still leaves about 9e21 arrangements over two layers versus 3e32 unconstrained. Not changing
   it unilaterally because it changes what the pending run measures.
2. **Batch width sweep.** You mentioned the clusters can run about 500 at once. Right now the array
   defaults to 16. To answer RQ3 properly I would add batch width as an explicit axis and run the
   same study at 1, 16 and 100+ so we can show where TPE stops beating random. That is more
   compute than the current plan. Worth it, or keep it qualitative?
3. **2D baseline channel width.** Still open from June. The 2D arch will not route at the width the
   3D arch uses, so the script probes 200, 300, 400 and reports which routed. Fine, or pin one?
4. **Venue, scope, framing.** Framing A or B from section 2, and is this a full paper, a short
   paper, or part of a larger journal version of Lay of the Layers? Mostly so I size sections
   correctly. Happy to own the API, setup and results sections plus all figures, and to draft the
   rest for you to reshape.

## 8. Ordering of work

1. **In progress, compute-free:** Figures 1 to 3 and Listing 1, Table 1, related work reading,
   and the resource-matching decision from question 1.
2. **In parallel, as soon as the rerun happens:** the campaign, then Tables 2 and 3 and Figure 4.
   The current sampling is fine to run as-is (block counts can be reported per trial and
   conditioned on in analysis), so this should not wait on question 1.
3. **Then:** cross-benchmark run for RQ4 and Figure 6, which decides how strong the story is.
4. **Then:** batch width sweep for RQ3 if we want it quantitative, then full draft.
