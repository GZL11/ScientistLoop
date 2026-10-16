---
name: scientific-writing
description: Academic manuscript writing with IMRAD structure, citation formatting, and reporting guidelines. Use when drafting or revising research papers.
metadata:
  category: writing
  trigger-keywords: "paper,manuscript,writing,IMRAD,citation,abstract,introduction,methods,results,discussion"
  applicable-stages: "16,17,19"
  priority: "2"
  version: "1.1"
  author: researchclaw
  references: "adapted from K-Dense-AI/claude-scientific-skills"
---

## Scientific Writing Best Practice

### Agent-first activation

Activate the paper-writing workflow only when the user asks for a paper,
manuscript, submission-ready draft, or venue-formatted deliverable. Do not
force venue selection or paper stages onto literature, experiment, coding, or
analysis requests.

Before drafting a venue-targeted paper:

1. Confirm the target venue, year, and paper type. Keep the source paper's
   publication venue separate from the intended submission venue.
2. Read the official author guidelines and template source. Requirements that
   cannot be verified must be marked `unknown`, never guessed.
3. Inspect a small, task-appropriate set of recent and closely related papers
   from the same venue. Extract writing patterns and evidence expectations;
   never imitate their wording.
4. Write a concise, source-backed brief to
   `planning/venue-writing-brief.md`. Include official sources, template and
   bibliography facts, section/figure/table/anonymity/page rules, exemplar
   papers, and unresolved requirements.
5. Use this brief while drafting and revising. It is a lightweight planning
   artifact, not a backend workflow object.

If the venue or official template is not confirmed, keep the manuscript as a
draft and state the uncertainty. Before calling a paper final, load
`latex-fmt`, run the available deterministic checks, and report their actual
severity.

### IMRAD Structure
1. **Abstract**: State objective, methods, key results, and conclusion in 150-300 words
2. **Introduction**: Move from broad context to specific gap to your contribution (funnel structure)
3. **Methods**: Sufficient detail for replication; use past tense, passive voice
4. **Results**: Present findings without interpretation; pair text with figures/tables
5. **Discussion**: Interpret results, compare with literature, acknowledge limitations, state implications

### Paragraph-Level Guidance
1. Each paragraph should convey ONE main idea
2. Open with a topic sentence; close with a transition to the next paragraph
3. Write in full flowing prose — never submit bullet points as final manuscript text
4. Use active voice for clarity: "We measured..." not "Measurements were taken..."
5. Vary sentence length; aim for average 15-25 words per sentence

### Citation Best Practices
1. Cite primary sources over reviews when making specific claims
2. Use citation styles consistently (APA, Vancouver, IEEE) per target journal
3. Every factual claim needs a citation unless it is common knowledge in the field
4. Avoid citation strings of 5+ references — select the most relevant 2-3
5. Self-citations should be limited to genuinely relevant prior work

### Common Writing Pitfalls
1. Avoid hedge-stacking: "It might possibly suggest..." — choose one hedge
2. Do not start sentences with "It is well known that" — cite or remove
3. Distinguish "significant" (statistical) from "substantial" (practical)
4. Ensure figures/tables are referenced in text BEFORE they appear
5. Keep abbreviations to a minimum; define each on first use

### Reporting Guidelines
1. Randomized trials: follow CONSORT checklist
2. Observational studies: follow STROBE checklist
3. Systematic reviews: follow PRISMA checklist
4. Diagnostic accuracy: follow STARD checklist
5. Always check target journal's author guidelines for specific requirements

### Revision Checklist
1. Verify all figures/tables are cited in text and numbered sequentially
2. Confirm reference list matches in-text citations exactly
3. Check that abstract accurately reflects the final manuscript content
4. Ensure methods section enables independent replication
5. Read aloud to catch awkward phrasing and run-on sentences
