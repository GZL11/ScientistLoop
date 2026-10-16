# NatureBench 当前结果与进度

本文档是 NatureBench 的**当前事实表**，不记录实验批次、历史比较或中间过程。每个
`case_id` 只出现一次；新结果通过数值完整性检查和 Validity Judge 后，直接修改对应行。

- 当前提交包入口：[`famou-glm52-official-current`](../../../.famou/naturebench-submissions/famou-glm52-official-current/)
- 历史实验记录：[`RUN_RESULTS_CN.md`](RUN_RESULTS_CN.md)
- 固定分母：90 个官方 case
- 状态阈值：`g < 0` 为未 Match，`0 <= g <= 0.1` 为 Match，`g > 0.1` 为 Surpass
- 最新 Validity Judge 口径：所有有正式 Run 的 case 均以 GPT-5.5 结论为准；Sonnet 只保留为历史证据。补判批次审计见
  [`gpt-5.5-formal-rejudge-20260820`](../../../.famou/naturebench-judge-reruns/gpt-5.5-formal-rejudge-20260820/README_CN.md)
  与 [`gpt-5.5-rejudge-invalid-v3-20260821`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-invalid-v3-20260821/)
  、[`gpt-5.5-rejudge-opus5-v1-20260825`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-opus5-v1-20260825/)
  、[`gpt-5.5-rejudge-opus5-v2345-20260826`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-opus5-v2345-20260826/)
  与 [`gpt-5.5-rejudge-opus5-m2s-20260826`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-opus5-m2s-20260826/)
- 更新时间：2026-08-28 CST

## 当前汇总

| 状态 | Case 数 | 占 90 个 case |
|---|---:|---:|
| 严格可信完成（GPT-5.5 Valid 且数值完整） | 86 | 95.56% |
| 数值结果不可信 | 1 | 1.11% |
| Judge Invalid（GPT-5.5） | 1 | 1.11% |
| 无正式结果 | 2 | 2.22% |
| 可信未 Match | 35 | 38.89% |
| 可信 Match-only | 29 | 32.22% |
| 可信 Surpass | 22 | 24.44% |
| 可信 Match-SOTA（含 Surpass） | 51 | 56.67% |

严格可信结果内的 Match-SOTA 比例为 `51/86 = 59.30%`。官方固定 90-case 分母下为
`51/90 = 56.67%`。所有纳入严格可信统计的 Judge 均为 `gpt-5.5`；旧 Sonnet verdict 仅保留作历史证据。

## 当前运行

正在运行：glm-5.3 能力对照第二批（10 个 case，`glm53b2-*-20260828`）。运行中的结果
不提前计入正式汇总；只有新 Run 形成完整有限分数且 Judge 为 Valid，才覆盖下方当前
正式结果。

**本次更新**：Opus-5 七个批次（`rerun-v3` + `opus5-v1`~`v5` + `opus5-m2s`，共 79 个
case）已全部完成 gpt-5.5 post-hoc Validity Judge，按「Valid 且分数最高」口径复核
全部 90 个 case，**本次替换 46 行**；主表中当前采用 Opus-5 Run 的合计 59 行
（其余 13 行来自更早已入账的 Opus 批次）。判定批次见
[`gpt-5.5-rejudge-opus5-v1-20260825`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-opus5-v1-20260825/)、
[`gpt-5.5-rejudge-opus5-v2345-20260826`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-opus5-v2345-20260826/)
与 [`gpt-5.5-rejudge-opus5-m2s-20260826`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-opus5-m2s-20260826/)。

其中 3 个原本不可采信的 case 通过合规重做转为 Valid：`s42256-022-00556-7`
（原 Judge Invalid，+0.1113 Surpass）、`s42256-023-00636-2`（原 Judge Invalid，
+0.0205 Match）、`s41592-025-02870-5`（原数值不可信，+0.1138 Surpass）。
`s43588-024-00730-4` 亦由 Invalid 转为 Valid，但新分数更低（-499.15），按不可信分数
无条件替换的规则采用。

Match-SOTA 由 38/90（42.22%）升至 **51/90（56.67%）**；其中 Surpass 由 11 升至 22。

**提交包尚未按本次结果重建**，其内容与判定仍为更新前口径，待重建后同步。

## 90-Case 当前主表

| Case | Domain | 当前状态 | 当前正式 g | Judge | 当前动作 | 当前采用 Run |
|---|---|---|---:|---|---|---|
| `s41467-025-63412-3` | Protein Biology | Match | 0.090402 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s41467-025-63412-3-20260826` |
| `s41467-025-63418-x` | Cellular Omics | 未 Match | -0.240325 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s41467-025-63418-x-glm52-20260808-001501` |
| `s41467-025-64512-w` | Protein Biology | Match | 0.037625 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v1-claude-opus-s41467-025-64512-w-20260824` |
| `s41467-025-65557-7` | Biomedical Modeling | Match | 0.023407 | Valid (GPT-5.5) | 已闭环 | `20260811-search-v2-s41467-025-65557-7` |
| `s41551-024-01257-9` | Biomedical Modeling | Match | 0.019004 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s41551-024-01257-9-20260826` |
| `s41551-024-01312-5` | Cellular Omics | Surpass | 0.139884 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s41551-024-01312-5-glm52-20260808-001501` |
| `s41551-025-01528-z` | Cellular Omics | Match | 0.008425 | Valid (GPT-5.5) | 已闭环 | `bio-all-v3-s41551-025-01528-z-glm52-20260808-175527` |
| `s41587-024-02414-w` | Cellular Omics | 未 Match | -0.022925 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s41587-024-02414-w-20260825` |
| `s41587-024-02428-4` | Protein Biology | 未 Match | -0.032284 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v1-claude-opus-s41587-024-02428-4-20260824` |
| `s41587-025-02585-0` | Biomedical Modeling | 未 Match | -0.509462 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s41587-025-02585-0-glm52-20260808-002848` |
| `s41587-025-02654-4` | Protein Biology | 未 Match | -0.463375 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v3-claude-opus-s41587-025-02654-4-20260825` |
| `s41587-025-02688-8` | Cellular Omics | Surpass | 1.335312 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s41587-025-02688-8-glm52-20260808-002848` |
| `s41592-022-01709-7` | Cellular Omics | 未 Match | -0.082152 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s41592-022-01709-7-20260825` |
| `s41592-023-01878-z` | Biomedical Modeling | 未 Match | -0.995935 | Valid (GPT-5.5) | 已闭环 | `configfix-s41592-023-01878-z-20260810-2120` |
| `s41592-023-01940-w` | Cellular Omics | 未 Match | -1.146056 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s41592-023-01940-w-glm52-20260808-012031` |
| `s41592-023-01955-3` | Cellular Omics | Surpass | 1.435272 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s41592-023-01955-3-20260826` |
| `s41592-023-02032-5` | Biomedical Modeling | 未 Match | -0.655801 | Valid (GPT-5.5) | 已闭环 | `datafix-r2-s41592-023-02032-5-20260810-192136` |
| `s41592-023-02035-2` | Cellular Omics | Match | 0.009133 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s41592-023-02035-2-20260826` |
| `s41592-023-02124-2` | Cellular Omics | Match | 0.050415 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s41592-023-02124-2-glm52-20260808-012031` |
| `s41592-023-02148-8` | Cellular Omics | Surpass | 0.279872 | Valid (GPT-5.5) | invalid-v3 合规重做，GPT-5.5 Valid | `invalid-v3-claude-deepseek-s41592-023-02148-8-20260820` |
| `s41592-024-02191-z` | Cellular Omics | Match | 0.036789 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v2-claude-opus-s41592-024-02191-z-20260825` |
| `s41592-024-02257-y` | Cellular Omics | 未 Match | -0.214275 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s41592-024-02257-y-20260825` |
| `s41592-024-02316-4` | Cellular Omics | Match | 0.030928 | Valid (GPT-5.5) | 已闭环 | `old-policy-search-v4-2x2x5-s41592-024-02316-4-20260813` |
| `s41592-024-02372-w` | Cellular Omics | 未 Match | -2.589572 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v5-claude-opus-s41592-024-02372-w-20260825` |
| `s41592-024-02523-z` | Cellular Omics | 未 Match | -0.025116 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v1-claude-opus-s41592-024-02523-z-20260824` |
| `s41592-024-02580-4` | Biomedical Modeling | 数值不可信 | -0.997676 | Valid (GPT-5.5) | 官方 GT 缺失，等待上游修复 | `required-rerun-s41592-024-02580-4-20260810-2100` |
| `s41592-025-02662-x` | Biomedical Modeling | 未 Match | -0.077484 | Valid (GPT-5.5) | v2 回退至 `-0.097490`，保留旧正式最佳 | `code-refresh-s41592-025-02662-x-20260810-1955` |
| `s41592-025-02665-8` | Biomedical Modeling | Match | 0.032417 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v1-claude-opus-s41592-025-02665-8-20260824` |
| `s41592-025-02776-2` | Protein Biology | Surpass | 0.139697 | Valid (GPT-5.5) | 已闭环 | `bio-all-v3-s41592-025-02776-2-glm52-20260808-175527` |
| `s41592-025-02820-1` | Protein Biology | 未 Match | -0.445322 | Valid (GPT-5.5) | Opus-5 提升，GPT-5.5 Valid | `rerun-v3-claude-opus-02820-1-20260820` |
| `s41592-025-02826-9` | Biomedical Modeling | 未 Match | -0.178774 | Valid (GPT-5.5) | 已闭环 | `old-policy-search-v4-2x2x5-s41592-025-02826-9-20260813` |
| `s41592-025-02854-5` | Cellular Omics | 未 Match | -0.583355 | Valid (GPT-5.5) | invalid-v3 合规重做，仍未 Match | `invalid-v3-claude-deepseek-s41592-025-02854-5-20260820` |
| `s41592-025-02870-5` | Cellular Omics | Surpass | 0.113778 | Valid (GPT-5.5) | opus-5 合规重做，GPT-5.5 Valid | `opus5-v4-claude-opus-s41592-025-02870-5-20260825` |
| `s41592-025-02886-x` | Biomedical Modeling | 未 Match | -56.453656 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v5-claude-opus-s41592-025-02886-x-20260825` |
| `s41592-025-02893-y` | Biomedical Modeling | 未 Match | -98.772782 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v5-claude-opus-s41592-025-02893-y-20260825` |
| `s41592-025-02924-8` | Cellular Omics | 未 Match | -0.038208 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s41592-025-02924-8-20260825` |
| `s41592-025-02926-6` | Cellular Omics | 未 Match | -0.217313 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v4-claude-opus-s41592-025-02926-6-20260825` |
| `s41592-025-02983-x` | Cellular Omics | Match | 0.050550 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s41592-025-02983-x-20260826` |
| `s42256-022-00447-x` | Molecular Design | Match | 0.058294 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-022-00447-x-20260826` |
| `s42256-022-00459-7` | Protein Biology | Match | 0.012041 | Valid (GPT-5.5) | 已闭环 | `bio-all-v3-s42256-022-00459-7-glm52-20260808-175527` |
| `s42256-022-00464-w` | Physical Modeling | Surpass | 0.230386 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v3-claude-opus-s42256-022-00464-w-20260825` |
| `s42256-022-00468-6` | Relational Reasoning | Match | 0.069003 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-022-00468-6-20260826` |
| `s42256-022-00501-8` | Molecular Design | 未 Match | -0.033963 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s42256-022-00501-8-20260825` |
| `s42256-022-00518-z` | Cellular Omics | Surpass | 0.201018 | Valid (GPT-5.5) | invalid-v3 合规重做，GPT-5.5 Valid | `invalid-v3-claude-deepseek-s42256-022-00518-z-20260820` |
| `s42256-022-00526-z` | Molecular Design | 未 Match | -0.091079 | Valid (GPT-5.5) | Opus-5 提升，GPT-5.5 Valid | `rerun-v3-claude-opus-00526-z-20260820` |
| `s42256-022-00534-z` | Cellular Omics | Match | 0.000434 | Valid (GPT-5.5) | v2 新增 Match | `rerun-v2c-claude-deepseek-00534-20260818` |
| `s42256-022-00541-0` | Biomedical Modeling | 未 Match | -0.145824 | Valid (GPT-5.5) | v2g 提升，仍未 Match | `rerun-v2g-claude-deepseek-00541-0-20260819` |
| `s42256-022-00556-7` | Relational Reasoning | Surpass | 0.111312 | Valid (GPT-5.5) | opus-5 合规重做，GPT-5.5 Valid | `opus5-v4-claude-opus-s42256-022-00556-7-20260825` |
| `s42256-023-00611-x` | Relational Reasoning | Match | 0.024295 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-023-00611-x-20260826` |
| `s42256-023-00619-3` | Protein Biology | Surpass | 0.124185 | Valid (GPT-5.5) | 已闭环 | `bio-all-v3-s42256-023-00619-3-glm52-20260808-175527` |
| `s42256-023-00627-3` | Cellular Omics | Surpass | 0.135835 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-023-00627-3-20260826` |
| `s42256-023-00628-2` | Physical Modeling | 未 Match | -0.034614 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v1-claude-opus-s42256-023-00628-2-20260824` |
| `s42256-023-00630-8` | Relational Reasoning | Surpass | 0.106016 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v4-claude-opus-s42256-023-00630-8-20260825` |
| `s42256-023-00636-2` | Molecular Design | Match | 0.020453 | Valid (GPT-5.5) | opus-5 合规重做，GPT-5.5 Valid | `opus5-v4-claude-opus-s42256-023-00636-2-20260825` |
| `s42256-023-00639-z` | Protein Biology | Surpass | 0.112367 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-023-00639-z-20260826` |
| `s42256-023-00640-6` | Molecular Design | Match | 0.027606 | Valid (GPT-5.5) | 已闭环 | `bio-all-v3-s42256-023-00640-6-glm52-20260808-175527` |
| `s42256-023-00654-0` | Molecular Design | 未 Match | -0.199075 | Valid (GPT-5.5) | Opus-5 提升，GPT-5.5 Valid | `rerun-v3-claude-opus-00654-0-20260820` |
| `s42256-023-00712-7` | Molecular Design | Judge Invalid | -0.021930 | Invalid (GPT-5.5) | 已闭环 | `nb-final-s42256-023-00712-7-glm52-20260809-all-remaining-v1` |
| `s42256-024-00790-1` | Physical Modeling | Match | 0.020292 | Valid (GPT-5.5) | Opus-5 新增 Match，GPT-5.5 Valid | `rerun-v3-claude-opus-00790-1-20260820` |
| `s42256-024-00795-w` | Protein Biology | 未 Match | -0.003817 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v1-claude-opus-s42256-024-00795-w-20260824` |
| `s42256-024-00815-9` | Molecular Design | Match | 0.029720 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-024-00815-9-20260826` |
| `s42256-024-00833-7` | Relational Reasoning | Match | 0.012810 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-024-00833-7-20260826` |
| `s42256-024-00836-4` | Cellular Omics | 未 Match | -0.137821 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s42256-024-00836-4-20260825` |
| `s42256-024-00838-2` | Protein Biology | 未 Match | -0.051995 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v3-claude-opus-s42256-024-00838-2-20260825` |
| `s42256-024-00892-w` | Biomedical Modeling | Match | 0.048711 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v1-claude-opus-s42256-024-00892-w-20260824` |
| `s42256-024-00916-5` | Molecular Design | 未 Match | -0.210000 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v3-claude-opus-s42256-024-00916-5-20260825` |
| `s42256-024-00956-x` | Physical Modeling | Surpass | 0.212052 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v3-claude-opus-s42256-024-00956-x-20260825` |
| `s42256-025-01002-0` | Protein Biology | Match | 0.039207 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-025-01002-0-20260826` |
| `s42256-025-01003-z` | Cellular Omics | 未 Match | -0.033083 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v1-claude-opus-s42256-025-01003-z-20260824` |
| `s42256-025-01010-0` | Molecular Design | 未 Match | -1.098003 | Valid (GPT-5.5) | Opus-5 提升，GPT-5.5 Valid | `rerun-v3-claude-opus-01010-0-20260820` |
| `s42256-025-01016-8` | Cellular Omics | Surpass | 0.408504 | Valid (GPT-5.5) | 已闭环 | `bio-all-v3-s42256-025-01016-8-glm52-20260808-175527` |
| `s42256-025-01019-5` | Protein Biology | 未 Match | -0.342834 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v4-claude-opus-s42256-025-01019-5-20260825` |
| `s42256-025-01026-6` | Protein Biology | Surpass | 0.177146 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s42256-025-01026-6-20260826` |
| `s42256-025-01042-6` | Protein Biology | 未 Match | -0.198697 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v3-claude-opus-s42256-025-01042-6-20260825` |
| `s43588-024-00689-2` | Cellular Omics | Surpass | 0.158822 | Valid (GPT-5.5) | 已闭环 | `bio-rerun-v1-s43588-024-00689-2-glm52-20260807-230900` |
| `s43588-024-00698-1` | Cellular Omics | Match | 0.007240 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s43588-024-00698-1-20260826` |
| `s43588-024-00703-7` | Physical Modeling | Surpass | 0.316538 | Valid (GPT-5.5) | 已闭环 | `nb-final-s43588-024-00703-7-glm52-20260809-all-remaining-v1` |
| `s43588-024-00716-2` | Protein Biology | Match | 0.014848 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v1-claude-opus-s43588-024-00716-2-20260824` |
| `s43588-024-00730-4` | Physical Modeling | 未 Match | -499.153480 | Valid (GPT-5.5) | opus-5 合规重做，GPT-5.5 Valid | `opus5-v5-claude-opus-s43588-024-00730-4-20260825` |
| `s43588-024-00732-2` | Physical Modeling | Surpass | 0.515045 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s43588-024-00732-2-20260826` |
| `s43588-024-00733-1` | Protein Biology | Match | 0.010213 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s43588-024-00733-1-20260826` |
| `s43588-024-00757-7` | Physical Modeling | 未 Match | -0.298638 | Valid (GPT-5.5) | opus-5 提升，仍未 Match | `opus5-v2-claude-opus-s43588-024-00757-7-20260825` |
| `s43588-024-00765-7` | Cellular Omics | Match | 0.087359 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-m2s-claude-opus-s43588-024-00765-7-20260826` |
| `s43588-025-00798-6` | Biomedical Modeling | Surpass | 0.175259 | Valid (GPT-5.5) | 已闭环 | `configfix-s43588-025-00798-6-20260810-2120` |
| `s43588-025-00842-5` | Physical Modeling | Surpass | 0.197531 | Valid (GPT-5.5) | 已闭环 | `nb-final-s43588-025-00842-5-glm52-20260809-all-remaining-v1` |
| `s43588-025-00872-z` | Physical Modeling | 无正式结果 | — | — | 待重跑闭环 | — |
| `s43588-025-00878-7` | Cellular Omics | 无正式结果 | — | — | 待重跑闭环 | — |
| `s43588-025-00903-9` | Physical Modeling | Match | 0.013125 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v3-claude-opus-s43588-025-00903-9-20260825` |
| `s43588-025-00917-3` | Physical Modeling | Surpass | 0.700497 | Valid (GPT-5.5) | opus-5 提升，已闭环 | `opus5-v4-claude-opus-s43588-025-00917-3-20260825` |
| `s43588-025-00920-8` | Physical Modeling | Match | 0.013787 | Valid (GPT-5.5) | Opus-5 新增 Match，GPT-5.5 判定分歧取 Valid | `rerun-v3-claude-opus-00920-8-20260820` |

## 维护规则

1. 新 Run 尚在运行时，只更新“当前运行”和对应行的“当前动作”，不修改正式分数。
2. 新 Run 必须满足：有限官方分数、Judge Valid、实例覆盖完整、关键指标有限且无
   `error`/`partial_errors`，才可覆盖当前正式结果。
3. 覆盖后同步修改本页汇总、对应 case 行及
   `.famou/naturebench-submissions/famou-glm52-official-current/`。
4. 批次对比、失败诊断和策略分析只写入 `RUN_RESULTS_CN.md`，不追加到本页。
