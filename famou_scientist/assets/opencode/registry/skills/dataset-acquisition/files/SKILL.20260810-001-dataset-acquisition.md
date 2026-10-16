---
name: dataset-acquisition
description: Prepare a real dataset for an experiment after the benchmark is selected. Use before experiment implementation or execution whenever data may need to be located, downloaded, authenticated, unpacked, or validated. Ask whether the user already has the data; otherwise confirm the download destination with the current run's experiment/data directory as the default. If acquisition cannot recover automatically, stop and ask the user with concrete options instead of silently continuing with synthetic data, placeholders, or paper writing.
metadata:
  category: experiment
  trigger-keywords: "dataset,data download,download data,数据集,下载数据,数据路径,数据准备,benchmark data"
  applicable-stages: "9,10,11"
  priority: "1"
  version: "20260810-001"
  author: researchclaw
---

# Dataset Acquisition

Own only the transition from a selected dataset to verified, readable local data. Benchmark choice stays in `benchmark-selection`; preprocessing and modeling stay in downstream experiment skills.

## 1. Start From Real State

Before asking or downloading:

1. Resolve the active run directory from the current experiment context.
2. Check user-provided paths and the default destination on disk.
3. Reuse existing complete data. Never redownload because a message or plan forgot the path.
4. Never substitute synthetic, toy, mock, or placeholder data unless the user explicitly chooses a feasibility-only study.

The default download root is:

```text
research-runs/<active-run>/experiment/data/
```

It is relative to the Agent's current workspace and must not be inferred from chat text.

## 2. Required User Checkpoint

If no verified local dataset path is already known, use the built-in structured question tool before downloading. Ask whether the user wants to:

- use an existing dataset and provide its path;
- download to the default `research-runs/<active-run>/experiment/data/` directory (recommended);
- download to a custom path.

Before the question, state the dataset name, official source, expected size, license/authentication requirements, and the intended subset when known. Do not hide a multi-terabyte download behind a generic confirmation.

If the user already supplied an unambiguous path or explicitly approved the default path in the current conversation, do not ask again; validate it and proceed.

## 3. Preflight

Before starting the transfer:

1. Confirm the official download method, not only a project homepage.
2. Check free disk space against the expected download and extraction size.
3. Inspect proxy variables (`HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, or the configured egress equivalent) without printing credentials.
4. Identify authentication, license acceptance, tokens, Globus/Kaggle/HuggingFace login, or manual approval requirements.
5. Prefer official clients, scripts, APIs, and documented mirrors. Preserve resumability for large downloads.

A short `curl` probe returning HTTP `000` is only a connectivity diagnostic. It is not evidence that the dataset is unavailable and must not be reported as a completed download failure.

## 4. Download Transparently

Tell the user when acquisition starts and what is being downloaded. Put commands, transfer logs, retries, and file-level progress in the process area; keep the chat update to source, destination, expected size, and meaningful state changes.

For large data:

- use resumable transfer where supported;
- download only the approved subset;
- avoid repeatedly polling or replaying the same transfer;
- keep partial data clearly distinguishable from verified complete data.

## 5. Verify Before Handoff

Do not mark acquisition complete just because a command exited with code 0. Verify what the source supports:

- expected files or shard count;
- non-zero sizes and plausible total size;
- checksums when published;
- archive integrity before destructive extraction;
- one minimal parser/read sample;
- required labels, splits, and metadata.

Record the verified path and any selected subset in `planning/design.md`. A downstream experiment may start only from this verified path.

## 6. Failure And User Handoff

Classify the actual failure first: transient network, proxy not inherited, DNS/TLS, wrong or expired URL, authentication/license, storage/quota, corrupted archive, or source-side outage.

Retry only when the failure is plausibly transient and the retry is safe. If the Agent cannot recover autonomously, it must:

1. stop the acquisition stage;
2. state the concise cause and what was actually attempted;
3. use the structured question tool with relevant choices, such as:
   - configure/fix the proxy and retry;
   - complete login or provide a token through the approved secret mechanism;
   - use an official alternate mirror;
   - provide an existing local dataset path;
   - pause data-dependent work;
4. wait for the user's answer.

An ordinary informational message is not sufficient for a blocker. Do not continue into real-data experiments, claim validation, Results writing, or a final paper while acquisition is unresolved.

## 7. Handoff Contract

Return these facts to `experimental-design` or the execution skill:

- dataset and version;
- verified local path;
- source and license/auth status;
- selected subset and split files;
- verification performed;
- remaining limitations.

Keep download mechanics out of the user-facing research conclusion once the handoff is complete.
