"""
agent_builder.py — 将 frontmatter 模板与 prompt 正文组装为最终 agent 文件

目录约定：
  runners/
    prompt_variants/
      baseline/
        famou-master.md   ← 纯正文，无 frontmatter
        famou-build.md
        famou-single.md   ← single agent 正文
      <variant>/
        famou-master.md   ← 只需放有变化的文件，缺失时继承 baseline
    configs/
      .claude/
        frontmatter/
          famou-master.txt  ← CC master frontmatter
          famou-build.txt   ← CC build frontmatter
        settings.json
      .claude-single/
        frontmatter/
          famou-single.txt  ← CC single agent frontmatter
        settings.json
      .opencode/
        frontmatter/
          famou-master.txt  ← 空（opencode master 无需 frontmatter）
          famou-build.txt   ← opencode build frontmatter
        opencode.jsonc
      .opencode-single/
        frontmatter/
          famou-single.txt  ← opencode single agent frontmatter
        opencode.jsonc

agent 名称从 agent_config_dir/frontmatter/*.txt 自动发现，
无需硬编码：.claude/ 有 master+build，.claude-single/ 只有 single。

组装结果写入 workspace/.opencode/agents/ 或 workspace/.claude/agents/。
"""

import shutil
from pathlib import Path

_RUNNERS_DIR = Path(__file__).parent
_DEFAULT_VARIANTS_DIR = _RUNNERS_DIR / "prompt_variants"
_DEFAULT_SKILL_SETS_DIR = _RUNNERS_DIR / "skill_sets"


def assemble_agents(
    agent_config_dir: Path,
    variant: str,
    workspace: Path,
    variants_dir: Path | None = None,
) -> None:
    """
    把 prompt variant 文件组装成最终 agents/ 目录，写入 workspace。

    agent_config_dir : runners/configs/.claude/ 等配置目录
    variant          : prompt_variants/ 下的子目录名（如 "default"）
    workspace        : agent 工作目录
    variants_dir     : prompt_variants/ 根目录，None 时用 runners/prompt_variants/

    agent 名称从 agent_config_dir/frontmatter/*.txt 自动发现，
    文件名（不含扩展名）即 agent 名称。
    """
    variants_root = variants_dir or _DEFAULT_VARIANTS_DIR
    default_dir = variants_root / "default"
    variant_dir = variants_root / variant
    frontmatter_dir = agent_config_dir / "frontmatter"

    # workspace 下的 agents/ 目录使用平台标准名（.opencode 或 .claude）
    platform_dir = _platform_dir(agent_config_dir)
    agents_dst = workspace / platform_dir / "agents"
    agents_dst.mkdir(parents=True, exist_ok=True)

    # 从 frontmatter/ 目录自动发现 agent 名称
    for frontmatter_file in sorted(frontmatter_dir.glob("*.txt")):
        agent_name = frontmatter_file.stem

        # 继承逻辑：variant 有就用，没有就用 default
        variant_file = variant_dir / f"{agent_name}.md"
        body_file = variant_file if variant_file.exists() else default_dir / f"{agent_name}.md"

        body = body_file.read_text(encoding="utf-8")
        frontmatter = frontmatter_file.read_text(encoding="utf-8")

        (agents_dst / f"{agent_name}.md").write_text(frontmatter + body, encoding="utf-8")


def _platform_dir(agent_config_dir: Path) -> str:
    """
    根据 agent_config_dir 名称推断平台标准目录名。
    .claude* → .claude，.opencode* → .opencode
    """
    name = agent_config_dir.name
    if name.startswith(".claude"):
        return ".claude"
    if name.startswith(".opencode"):
        return ".opencode"
    return name


def copy_skills(
    skill_set: str,
    agent_config_dir: Path | None,
    workspace: Path,
    skill_sets_dir: Path | None = None,
    *,
    platform: str | None = None,
) -> None:
    """
    将 skill_set 下的所有 skill 目录复制到 workspace 的平台原生路径。

    skill_set      : skill_sets/ 下的子目录名（"none" 时跳过，不注入任何 skill）
    agent_config_dir: 用于推断平台（.claude* → .claude/skills/，.opencode* → .opencode/skills/）
                      可为 None（此时须通过 platform 显式指定）
    workspace      : agent 工作目录
    skill_sets_dir : skill_sets/ 根目录，None 时用 runners/skill_sets/
    platform       : 显式指定平台目录名（如 ".claude"），优先于 agent_config_dir 推断
    """
    if skill_set == "none":
        return

    root = skill_sets_dir or _DEFAULT_SKILL_SETS_DIR
    src = root / skill_set
    if not src.exists():
        raise FileNotFoundError(f"skill_set 不存在: {src}")

    platform_name = platform or _platform_dir(agent_config_dir)
    dst = workspace / platform_name / "skills"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def copy_base_config(agent_config_dir: Path, workspace: Path) -> None:
    """
    复制 agent_config_dir 中的基础配置文件（opencode.jsonc / settings.json）到 workspace，
    目标目录使用平台标准名（.opencode 或 .claude），跳过 agents/ 和 frontmatter/。
    node_modules 不复制——opencode runtime 进 workspace 后会自己 install @opencode-ai/plugin。
    """
    dst = workspace / _platform_dir(agent_config_dir)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        agent_config_dir,
        dst,
        ignore=shutil.ignore_patterns("agents", "frontmatter", "node_modules"),
    )
