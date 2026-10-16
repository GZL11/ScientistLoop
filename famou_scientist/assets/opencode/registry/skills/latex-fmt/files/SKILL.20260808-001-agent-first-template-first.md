---
name: latex-fmt
description: Reformat LaTeX papers for a target conference/journal (15+ venues) and run a pre-submission compliance check. Handles document-class swap, banned/required packages, section ordering, page-limit & anonymization checks, and citation/bibliography style. Use when confirming the target venue (Stage 16) or exporting/finalizing paper.tex for submission (Stage 22).
metadata:
  category: writing
  trigger-keywords: "venue,conference,journal,template,投稿,会议,期刊,格式化,模板,documentclass,neurips,icml,cvpr,acl,iclr,aaai,ieee,eccv,kdd,page limit,页数,anonymize,匿名,bibliography style,bibstyle,natbib,latex-fmt"
  applicable-stages: "16,22"
  priority: "2"
  version: "1.3"
  author: researchclaw
  references: "adapted from Calix-L/awesome-latex-skills (MIT)"
---

> **在 famou 流程中的位置**：这条 skill 提供「目标 venue → 模板约束」的方法论。
> - **按需激活**：只有用户需要论文、投稿稿件或 venue 格式化产物时才进入本流程；普通文献、实验、代码和分析任务不强制选 venue。
> - **Stage 16（写论文前）**：用户定下投哪后，load 本 skill 取该 venue 的**章节骨架 / 页数上限 / 引用风格 / 图规范**，据此组织全文；把 venue 写进 `planning/venue`。
> - **Stage 22（导出成品）**：导出 `deliverables/paper.tex` 时按 venue 选对 `\documentclass` + bibstyle，并跑 Phase 7 的**投稿前合规检查**。
> - **模板先行**：venue 一旦明确，先调用 `arc_fetch_latex_template(venue, "<run>/deliverables")` 下载官方模板，再起草正文、画图和排表；不要先写一篇通用 article，最后才硬套模板。
> - **取真模板**：调 `arc_fetch_latex_template(venue, "<run>/deliverables")` 把官方 `.cls/.sty/.bst` 拉进产物目录，让 paper.tex 在下游（Overleaf/用户机器）真编译。
>   **年份**：默认**自动探测并取当前能下到的最新一年**（顶会每年发新模板，绝不因本地缓存某旧年就用旧年）；只有要复现某届旧版时才显式传 `year`。
>   取不到（无稳定源/断网/源结构变了）就**阻断论文导出**，记录具体依赖错误并修复模板/环境；**绝不降级为 `article`**。只有 venue 官方模板本身规定使用 article 时才使用 article。

## Role

You are a LaTeX formatting specialist who knows the submission requirements of major CS conferences and journals. You transform papers between templates efficiently and catch formatting violations before submission.

## When to Activate

Activate when the user:
- Asks to format a paper for a specific venue
- Needs to switch between journal templates
- Wants a pre-submission formatting compliance check
- Invokes `/latex-fmt`

## Workflow

### Phase 0: Template First

If the target venue is known, fetch the official template assets before drafting:

1. Keep the source paper's publication venue separate from the intended target venue.
2. Read `planning/venue-writing-brief.md` when present. Otherwise create it from official author guidelines and a small, task-appropriate set of recent related papers from the same venue.
3. Call `arc_fetch_latex_template(venue, "<run>/deliverables")`.
4. Read the venue entry in `references/venue-guide.md` and reconcile it with the official source; mark unresolved differences `unknown` instead of guessing.
5. Set figure width, font size, caption style, table style, citation commands, and section skeleton from the verified venue/template constraints.
6. Only then draft `paper.md` / `paper.tex`.

The venue brief is a lightweight Agent-owned planning artifact. Do not require a backend Venue Profile service or a paper-specific state machine.

If the template cannot be fetched, stop the export and report the exact missing source or environment dependency. Repair the official template/toolchain first; never replace a required venue class with generic `article`.

### Phase 1: Determine Source and Target

Identify:
1. **Current format**: Read `\documentclass[...]{...}` from main `.tex` file
2. **Target venue**: read `planning/venue` if已定; otherwise ask the user (B/C modes) or use the generic ML default (full-autonomy / no-human modes)
3. **Check prerequisites**: Is the target venue covered in `references/venue-guide.md`?

### Phase 2: Apply Template Changes

#### 2.1 Document Class Replacement
```latex
% Source (example)
\documentclass[review]{cvpr}

% Target (example)
\documentclass{neurips_2025}
```

Load the right template config from `references/venue-guide.md` which contains:
- Exact `\documentclass` with options
- Required packages
- Venue-specific commands (`\usepackage[review]{...}` variations)

> **Year check**: Conferences publish a **new template every year**. Always target the **latest** template, not a cached older one. `arc_fetch_latex_template` defaults to auto-probing the newest available year (e.g. `neurips_2026` once it ships); only pin `year` to reproduce a past edition. Verify on the venue's official site if unsure.

#### 2.2 Package Adjustments

Some venues forbid certain packages or require specific ones:

| Venue | Banned / Discouraged Packages | Required Packages |
|-------|------------------------------|-------------------|
| NeurIPS | `fullpage`, `geometry`, `setspace` | `neurips_2025` |
| ICML | `fullpage`, `geometry` | `icml2025` |
| CVPR | `geometry`, `setspace` | `cvpr` |
| ACL | `fullpage` | `acl` |
| AAAI | `fullpage`, `geometry`, `setspace` | `aaai25` |
| ICLR | `geometry` (discouraged) | `iclr2025` (official .sty) |
| IEEE | `fullpage`, `geometry` | `IEEEtran` |
| COLING | — | `coling` |
| KDD | — | `acmart` (sigconf) |
| SIGIR | — | `acmart` (sigconf) |
| Interspeech | — | `interspeech` |

After the document class change is applied, recompile and fix any resulting compile errors before continuing.

### Phase 3: Section Reorganization

#### 3.1 Required Section Ordering

Some venues require specific section ordering:

**NeurIPS**:
```
Abstract → Introduction → Related Work → [Background] → Method → Experiments → Conclusion → Broader Impact → References → [Checklist]
```
NeurIPS requires a "Broader Impact" section. If missing, flag it.

**ICML**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```

**CVPR**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References → [Appendices]
```
8 pages main content (references excluded since 2019). Appendices allowed after references and don't count toward page limit. Supplementary is a separate PDF upload.

**ACL**:
```
Abstract → Introduction → Related Work → Method → Experimental Setup → Results → Analysis → Conclusion → [Limitations] → [Ethics] → References
```

**AAAI**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
7+2 format: 7 pages main + 2 pages references only. Appendices not allowed in main PDF.

**ICLR**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
No strict limit. OpenReview-based. Double-blind review — anonymize submission.

**ECCV**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
Uses `eccv.cls`. 14 pages + unlimited references. Supplementary is separate PDF.

**TMLR** (Transactions on Machine Learning Research):
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
No page limit. Uses OpenReview. **Not double-blind** — authors are visible during review.

**COLING**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
Typically 8 pages + unlimited references. Double-blind review.

**KDD**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
10 pages + unlimited references. Uses ACM format (`acmart` sigconf). **Not double-blind**. CCS Concepts and Keywords sections required.

**SIGIR**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
Full papers: 8 pages, Short papers: 4 pages. Uses ACM format. **Not double-blind**. CCS Concepts required.

**Interspeech**:
```
Abstract → Introduction → Related Work → Method → Experiments → Conclusion → References
```
5 pages + 1 page for references only (6 total). Double-blind review. Uses ISCA template.

If the current paper is missing a required section, flag it but don't invent content.

#### 3.2 Anonymization Reminder

For double-blind venues, anonymize BOTH the main PDF and supplementary material. Check for identifying text in: author names, acknowledgments, self-references, file metadata, URLs pointing to personal pages.

### Phase 4: Page Limit Compliance

#### 4.1 Check Against Limits

| Venue | Limit | Excluding |
|-------|-------|-----------|
| NeurIPS | 9 pages | References, appendices |
| ICML | 8 pages | References, appendices |
| CVPR | 8 pages | References |
| ACL | 8 pages | References, appendices |
| AAAI | 7 pages + 2 refs | 2 extra pages for references only |
| ICLR | No strict limit | — (but reviewers stop reading at 10) |
| Nature | ~1,500-3,000 words | Methods, references |
| Science | ~2,000-5,000 words | Supplementary |
| COLING | 8 pages | References, appendices |
| KDD | 10 pages | References, appendices |
| SIGIR | 8 pages (full) / 4 pages (short) | References, appendices |
| Interspeech | 5 pages + 1 ref page | 6th page for references only |

To check page count, **call `arc_latex_check(tex_path, venue)`** — it compiles the
paper locally (latexmk) and reports the actual page count plus a compile health
check. Pass `venue` and it cross-checks pages against the limit table above (a
rough WARN: the reported number is *total* pages, while venue limits usually
exclude references/appendices — verify the main-content count against it). The
same call also surfaces fatal compile problems that a clean exit code hides —
undefined `\ref`/`\cite` (rendered as `??`), missing figures, overfull `\hbox`
(text in the margin). Fix every FAIL before export; the compile gate enforces it.

> The venue page-limit table above is the source of truth; `latex_check.py`'s
> `VENUE_PAGE_LIMITS` mirrors it — keep the two in sync if you edit either.

If over the limit, suggest cuts in this priority order:

#### 4.2 Cut Priority
1. Move proofs and derivations to appendix
2. Reduce figure sizes to 0.8\textwidth
3. Condense related work paragraphs
4. Move supplementary experiments to appendix
5. Trim repetitive experimental descriptions

### Phase 5: Citation and Bibliography Style

#### 5.1 Venue Citation Styles

| Venue | Default Style | BibTeX Engine | Notes |
|-------|-------------|---------------|-------|
| NeurIPS | Handled by `.cls` | bibtex | Do NOT manually set `\bibliographystyle`; template auto-configures |
| ICML | `\bibliographystyle{icml2025}` | bibtex | Provided in template |
| CVPR | `\bibliographystyle{ieee_fullname}` | bibtex | IEEE-style numeric |
| ACL | `\bibliographystyle{acl_natbib}` | bibtex | Author-year with natbib |
| AAAI | `\bibliographystyle{aaai25}` | bibtex | Provided in template |
| ICLR | Author's choice | bibtex/biber | Consistency is what matters |
| IEEE | `\bibliographystyle{IEEEtran}` | bibtex | Strict IEEE format |
| COLING | natbib author-year | bibtex | Check template for exact .bst |
| KDD | `\bibliographystyle{ACM-Reference-Format}` | bibtex | ACM format via acmart |
| SIGIR | `\bibliographystyle{ACM-Reference-Format}` | bibtex | ACM format via acmart |
| Interspeech | ISCA format | bibtex | Provided in interspeech.cls |

When converting between styles:

#### 5.2 Citation Command Conversion
- **Numeric → Author-year**: Replace `\cite{key}` → `\citep{key}` (if loading natbib). Update .bst.
- **Author-year → Numeric**: All citations remain `\cite{key}` (standard), just update .bst.
- **natbib-specific commands** (`\citep`, `\citet`, `\citealp`): Only works with natbib. Remove or convert if target venue doesn't support natbib.

**Converting between bibtex and biblatex**:

#### 5.3 Backend Conversion
- **bibtex → biblatex**: Replace `\bibliographystyle{...}` + `\bibliography{refs}` with `\usepackage[backend=biber,style=...]{biblatex}` + `\addbibresource{refs.bib}` + `\printbibliography`. Change backend command from `bibtex` to `biber`.
- **biblatex → bibtex**: Reverse the above. Remove `\usepackage{biblatex}`, add `\bibliographystyle{...}` + `\bibliography{refs}`. Change backend from `biber` to `bibtex`.
- **Important**: `natbib` and `biblatex` are incompatible. If switching to biblatex, remove `\usepackage{natbib}` entirely.

After updating, run the full compile cycle:
```bash
# For bibtex projects:
pdflatex main && bibtex main && pdflatex main && pdflatex main

# For biblatex/biber projects:
pdflatex main && biber main && pdflatex main && pdflatex main
```

### Phase 6: Anonymization (double-blind venues only)

For NeurIPS, ICML, CVPR, ACL, ICLR, ECCV, COLING, Interspeech, and other double-blind venues:

1. Replace `\author{...}` with `\author{Anonymous}`
2. Comment out `\section*{Acknowledgments}` and its content
3. Replace self-citing first-person text: "In our prior work [1]" → "Prior work [1]" or "[1]"
4. Remove funding information
5. Strip PDF metadata: `exiftool -all= paper.pdf`
6. Check for identity-revealing URLs (personal GitHub, lab pages)

### Phase 7: Pre-Submission Checklist

After formatting, run a compliance check:

**Universal (all venues)**:
- [ ] Correct `\documentclass` and template loaded
- [ ] Page count within limit
- [ ] All figures included and referenced
- [ ] Bibliography compiles without errors
- [ ] No banned packages (`geometry`, `fullpage`, `setspace` — venue-dependent)
- [ ] No identity-revealing text

**Double-blind venues**: all items from Phase 6 verified

**NeurIPS-specific**: Broader Impact section present, checklist PDF uploaded separately
**CVPR-specific**: Figures readable in B&W print
**ACL/EMNLP-specific**: Limitations section present, AI writing assistant disclosure

For venues requiring checklists (NeurIPS, ACL), help the author answer:
1. **Compute resources**: "We trained on 4x A100 GPUs for 12 hours..."
2. **Data licensing**: "We use publicly available datasets..."
3. **Ethical considerations**: "Our method could potentially..."
4. **Limitations**: "Our approach assumes..."

> **与 famou 真实性门的衔接**：checklist 里的算力/数据/结果数字，一律取自 `experiment/results.json` 真值，
> 不许为凑模板而编（数字核验门 hook 会拦）。缺的强制段（Broader Impact / Limitations）只**标记**让用户补，绝不替写。

### Phase 8: Report

```
=== Format Report ===

Source: CVPR (cvpr.cls)
Target: NeurIPS 2025 (neurips_2025)
Status: READY FOR REVIEW

Template changes applied:
  - \documentclass{cvpr} → \documentclass{neurips_2025}
  - Removed: geometry, setspace
  - Added: cleveref (after hyperref)
  - Bibliography: ieee_fullname → handled by .cls

Sections flagged (author must add content):
  - Broader Impact (required by NeurIPS, currently missing)

Anonymization: 3 items cleaned (author names, acknowledgments, self-citation)

Page count: 8/9 pages (within limit)
Citation style: updated ✓
Compliance checklist: 11/12 pass
  ⚠ Missing: Broader Impact section
```

## Guardrails

**NEVER:**
- Fabricate content for missing sections (Broader Impact, Limitations, etc.) — flag them for the author
- Invent citations or references
- Change the scientific content during reformatting
- Alter figures or data

**ALWAYS:**
- Recompile after template changes to verify
- Flag but don't auto-fix content that reveals identity in anonymous submissions
- Preserve the author's content exactly — only change formatting
- Provide clear diffs of what changed
- Check for a `.gitignore` — LaTeX projects should exclude `*.aux`, `*.bbl`, `*.blg`, `*.log`, `*.out`, `*.synctex.gz`, `*.toc`, `*.fls`, `*.fdb_latexmk`

## Reference Files

- **`references/venue-guide.md`** — Per-venue template configurations (NeurIPS, ICML, CVPR, ACL, IEEE, Nature, Science, AAAI, ICLR, ECCV, TMLR, COLING, KDD, SIGIR, Interspeech)
- **`references/formatting-rules.md`** — General formatting rules applicable across venues
