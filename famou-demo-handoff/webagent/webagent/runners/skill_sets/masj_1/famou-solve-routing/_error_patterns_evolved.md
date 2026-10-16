# Consolidated Failure Analysis

## No Patches Provided

**Input received:** 0 diagnostic patches.

No failure modes can be identified, grouped, or prioritized because no patch data was supplied for analysis.

---

### Required Input

To produce a meaningful consolidated failure analysis, please provide:

1. **Individual patch contents** — the diagnostic text from each failed optimization run
2. **Minimum useful sample size** — ideally 5+ patches to detect meaningful patterns (frequency-based prioritization is unreliable below this threshold)
3. **Optional context** — task description, optimization target, and what "failure" means in this domain (e.g., constraint violation, incorrect output, timeout, suboptimal score)

### Once Patches Are Provided

The output will follow this structure for each identified failure mode:

```
## <Failure Mode Name>
**Prevalence:** [N/total runs]
**Root cause:** <one-sentence summary>
**Consolidated fix:** <concrete, actionable instruction>
```

Failure modes appearing in only 1 run will be briefly listed under a "One-off observations" section rather than featured.

Please resend with the patch contents included.