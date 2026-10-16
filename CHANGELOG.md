Changelog
===
以下记录了项目中所有值得关注的变更内容，其格式基于[Keep a Changelog]。

本项目版本遵守[Semantic Versioning]和[PEP-440]。

[Unreleased]
---
### Added
- 从 AutoResearchClaw（ARC）剥离科研能力，沉淀为自包含的 OpenCode 插件：
  - **真执行 tool**（`assets/opencode/tool/arc.ts`）：文献检索、实验执行、引用核验、批量引用核验
  - **质量护栏 hook**（`assets/opencode/plugins/guardrails.ts`）：实验质量门、引用核验门、论文数字核验门
  - **Python 内核**（`assets/opencode/scripts/`）：从 ARC 剥离的 literature/sandbox/verify 逻辑，
    纯 stdlib 自包含，已剪断 `researchclaw` 依赖
  - **28 个方法论 skill** + **AGENTS.md** 编排 + **opencode.json** 配置
- **CLI**：`famou-scientist` 命令（体检 → 注入资产环境 → 拉起 OpenCode TUI），
  含 `doctor` 子命令；模型凭证由用户自行 `opencode auth`，不写入任何文件
### Changed
- `cmdline.py` 从 hello-world 占位改为真正的启动器；移除 `demo.py`
- `pyproject.toml`：打包 `assets/**`；运行依赖清零（内核纯 stdlib）

0.1.0 - 2026-06-10
---
### Added
- 创建项目


[Unreleased]: https://github.com/GZL11/ScientistLoop/merge/0.1.0...master

[Keep a Changelog]: https://keepachangelog.com/zh-CN/1.0.0/
[Semantic Versioning]: https://semver.org/lang/zh-CN/
[PEP-440]: https://www.python.org/dev/peps/pep-0440/
