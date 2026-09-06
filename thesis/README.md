# TFG Thesis — LaTeX Project

Bachelor Thesis document (UC3M, Data Science and Engineering) for **The Lab**:
*Context-Aware Multi-Agent Orchestration: A Standardized Architecture via MCP for Autonomous
Agentic Systems* (official registered title). The system demonstrator is named *The Lab*
throughout the document.

Structure: **six research questions** (system RQ1–RQ3, agentic RQ4–RQ6) and
**four experiments** (1 three-ways-in + provider dimension, 2 S&P real-data
validation, 3 grounded-autonomy agentic round, 4 ten-Kaggle post-validation).

Built on the **official UC3M TFG LaTeX template in English** (Biblioteca UC3M, IEEE style,
PDF/A output, biblatex-ieee + biber).

## Build

```bash
scripts/build_thesis.sh            # pdflatex + biber + pdflatex x2 -> thesis/main.pdf
scripts/build_thesis.sh --clean    # remove aux files first
```

Requirements: any TeX Live distribution (`pdflatex`, `biber`). A TinyTeX install works:

```bash
wget -qO- https://yihui.org/tinytex/install-bin-unix.sh | sh
~/.TinyTeX/bin/x86_64-linux/tlmgr install txfonts pdfx colorprofiles biblatex biber \
  biblatex-ieee csquotes titlesec titletoc floatrow multirow pgf appendix booktabs \
  makecell enumitem needspace ragged2e colortbl float everyshi babel-english chngcntr \
  logreq xstring xpatch
```

On systems where `biber` fails with `libcrypt.so.1 ... GLIBC_2.2.5 not found`, extract
`libxcrypt-compat` into `~/.local/lib` (the build script picks it up automatically):

```bash
curl -sL https://archlinux.org/packages/core/x86_64/libxcrypt-compat/download/ -o /tmp/pkg.tar.zst
bsdtar -xf /tmp/pkg.tar.zst -C /tmp && cp /tmp/usr/lib/libcrypt.so.1.1.0 ~/.local/lib/libcrypt.so.1
```

The project also opens as-is on Overleaf (search "Bachelor thesis template UC3M IEEE" or
upload this folder; PDF/A + xmpdata are optional there).

## Layout

| Path | Content |
|---|---|
| `main.tex` | UC3M template: cover, abstract, indices, chapter includes |
| `main.xmpdata` | PDF/A metadata (edit with the cover fields) |
| `chapters/abstract.tex` | Summary + keywords (IEEE taxonomy terms) |
| `chapters/ch1..ch8` | Introduction, Background, Design, Implementation, Methodology, Results, Discussion, Conclusions |
| `chapters/annexes.tex` | Annex A (reproduction guide), B (real manifest), C (notebook), D (Exp. 4 datasets) |
| `figures/` | TikZ is inline; exported charts/screenshots go here |
| `bibliografia/bibliografia.bib` | IEEE-style bibliography (50 cited entries) |

## TODO inventory (fill before submission)

Marked with `\fillme{...}` (red) and `\resultslot{...}` boxes in the PDF.

**Cover (main.tex)**

- [ ] Author's full name
- [ ] Tutor's full name
- [ ] Defense date (and place, if different from Leganés)
- [ ] `main.xmpdata`: same fields

**Experiment 3 — grounded autonomy / agentic round (Section 6.5)** — FILLED from live recordings

- [x] RQ4/RQ5/RQ6 tables filled from live GLM recordings (iris, housing, churn ×3)
- [x] RQ5 spike confirmed at scale; offline Ollama proof (§6.10) and mixed-team
      per-stage assignment (§6.11) recorded
- [x] GLM-uniform ablation: validator + repair loop as capability enabler

**Experiment 4 — multi-domain stress validation (Section 6.6 + Annex D)** — FILLED

- [x] Arm A (6 datasets): churn +5.65, california +2.21, titanic +1.68,
      S&P +4.47, HR tie (baseline improved to 0.8707), e-commerce ceiling tie
- [x] Arm B (4 datasets): clinvar +0.26, kidney +1.81, crypto +1.86 (2/3
      absorbed each); energy 0/3 absorbed (honest refusal at RF+calendar 0.9590)
- [x] Ratchet scoreboard: 10 datasets, 37 generations, 53 rounds, 19
      replay-verified champions, 6 honest refusals
- [x] Prediction sweep FULL: 17 champions × 3 surfaces, 17/17 identical
- [x] P6 findings harvest: 15 tickets (9 applied)
- [ ] Deferred tiers (recorded as future work): NLP featurization, music
      signals, bitcoin scale stress, clustering/graph track

**Screenshots (UI — figures 3.x / 6.x)**

- [ ] A: Data view (deterministic folder) — `fig:ui-data`
- [ ] B: Experiments view with stage pipeline + agentic round — `fig:ui-experiments`
- [ ] C: Chat drawer with tool timeline — `fig:ui-chat`

**Bibliography polish**

- [ ] Complete real author lists for 4 entries with placeholder authors:
      `zhang2026breakingprotocol`, `hou2026mcplandscape`, `zhao2026tmlbench`,
      `jing2024dsbench`

**Optional polish**

- [ ] Dedication (currently a one-line placeholder; delete `Dedication` block if unwanted)
- [ ] Verify tutor-required deviations from the library guide
- [ ] After Arm B fill-ins: rebuild (current: 95 pages)

## Page-count map (current)

Front matter ~6 pp (roman) · Ch.1 ~5 · Ch.2 ~11 · Ch.3 ~16 · Ch.4 ~9 · Ch.5 ~8 ·
Ch.6 ~16 (incl. §6.1 evidence-base tables + 3 charts) · Ch.7 ~10 · Ch.8 ~3 ·
Bibliography ~3 · Annexes ~7.
**Compiles to 98 pages** with all recorded results integrated (Exp 3 + Exp 4 Arms A and B).