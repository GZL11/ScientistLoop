#!/usr/bin/env python3
"""为隔离的 NatureBench fm-job 运行准备公开文件快照。"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path


_EXCLUDED_REPOSITORY_NAMES = {
    ".git",
    ".famou",
    ".pytest_cache",
    "__pycache__",
    "assets",
    "docs",
    "node_modules",
    "output",
    "research-runs",
    "tests",
    "vis",
}

# 这些文件包含官方评分、Judge 或可信响应签名逻辑，只能在 Trusted
# Evaluator 可信进程从完整源码加载这些文件，不能进入 Agent 的源码快照。
_TRUSTED_ONLY_REPOSITORY_FILES = {
    "evaluator_worker.py",
    "evaluate_task.py",
    "judge_adapter.py",
    "trajectory_adapter.py",
}

_ALLOWED_CLAUDE_ENV_NAMES = {"API_TIMEOUT_MS"}
_ALLOWED_CLAUDE_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_")
_ALLOWED_JUDGE_ENV_PREFIXES = ("ANTHROPIC_", "JUDGE_")

# Public data contracts that must be checked before an Agent starts. These are
# limited to facts visible in the public task package; they never read hidden
# evaluator ground truth.
_PUBLIC_TASK_CONTRACTS = {
    "s42256-023-00628-2": {
        "relative_dir": Path("data/band_gap/test"),
        "extension": ".graphdata",
        "expected_count": 2037,
    },
}


def _ignore_repository_files(directory: str, names: list[str]) -> set[str]:
    """排除版本库元数据、缓存和历史运行产物。"""
    del directory
    return {
        name
        for name in names
        if (
            name in _EXCLUDED_REPOSITORY_NAMES
            or name in _TRUSTED_ONLY_REPOSITORY_FILES
            or name.endswith(".pyc")
        )
    }


def _ignore_trusted_repository_files(directory: str, names: list[str]) -> set[str]:
    """可信运行时只排除缓存和历史产物，保留 evaluator 实现。"""

    del directory
    return {
        name
        for name in names
        if name in _EXCLUDED_REPOSITORY_NAMES or name.endswith(".pyc")
    }


def _copy_directory(
    source: Path,
    destination: Path,
    *,
    repository: bool = False,
    exclude_top_level: set[str] | None = None,
) -> None:
    """复制真实目录并拒绝用符号链接代替隔离边界。"""
    if not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")
    if destination.exists():
        raise FileExistsError(f"run destination already exists: {destination}")
    excluded = set(exclude_top_level or ())
    ignore_base = _ignore_repository_files if repository else None

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(ignore_base(directory, names)) if ignore_base else set()
        if excluded and Path(directory).resolve() == source.resolve():
            ignored.update(name for name in names if name in excluded)
        return ignored

    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=ignore if (ignore_base or excluded) else None,
    )


def _copy_trusted_runtime(source: Path, destination: Path) -> None:
    """复制包含评测适配代码的可信 Famou 运行时。"""

    if destination.exists():
        raise FileExistsError(f"trusted runtime already exists: {destination}")
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=_ignore_trusted_repository_files,
    )


def _copy_task_without_problem(source: Path, destination: Path) -> None:
    """复制可信 task 的 evaluator 等内容，但不重复复制公开 problem。"""

    if destination.exists():
        raise FileExistsError(f"trusted task already exists: {destination}")

    source_root = source.resolve()

    def ignore_problem(directory: str, names: list[str]) -> set[str]:
        """只在 task 根目录排除 problem，其他同名文件不受影响。"""

        if Path(directory).resolve() == source_root and "problem" in names:
            return {"problem"}
        return set()

    shutil.copytree(source, destination, symlinks=False, ignore=ignore_problem)


def _validate_problem_snapshot(
    source: Path,
    manifest_path: Path,
    *,
    agent_uid: int,
    agent_gid: int,
) -> None:
    """验证可复用的公开题面快照及其既有审计清单。"""

    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"problem snapshot 必须是真实目录: {source}")
    source_stat = source.stat()
    source_mode = stat.S_IMODE(source_stat.st_mode)
    if source_mode & 0o002:
        raise PermissionError(f"problem snapshot 对任意用户可写: {source}")
    if source_stat.st_gid == agent_gid and source_mode & 0o020:
        raise PermissionError(f"problem snapshot 对 Agent 组可写: {source}")
    if source_stat.st_uid == agent_uid and source_mode & 0o200:
        raise PermissionError(f"problem snapshot 由 Agent 所有且可写: {source}")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"problem snapshot 审计清单不存在: {manifest_path}")

    # 清单可能覆盖百万级文件，采用流式名称检查，不把 40+ MiB JSON 全部载入内存。
    forbidden_fragments = ('"path": "evaluation/', '"path": "ground_truth/')
    with manifest_path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if any(fragment in line for fragment in forbidden_fragments):
                raise RuntimeError("problem snapshot 清单包含隐藏 evaluator 数据")


def _public_contract_errors(task_id: str, problem_dir: Path) -> list[str]:
    """检查任务公开输入是否满足已知、可审计的文件契约。"""

    contract = _PUBLIC_TASK_CONTRACTS.get(task_id)
    if contract is None:
        return []
    data_dir = problem_dir / contract["relative_dir"]
    if not data_dir.is_dir():
        return [f"公开数据目录不存在: {data_dir.relative_to(problem_dir)}"]
    extension = str(contract["extension"])
    actual = sorted(path for path in data_dir.glob(f"*{extension}") if path.is_file())
    expected_count = int(contract["expected_count"])
    errors: list[str] = []
    if len(actual) != expected_count:
        errors.append(
            f"{data_dir.relative_to(problem_dir)} 中 {extension} 文件数为 {len(actual)}，"
            f"期望 {expected_count}"
        )
    if task_id == "s42256-023-00628-2":
        stems = {path.stem for path in actual}
        for companion in (".grid", ".griddata16"):
            missing = [
                stem
                for stem in stems
                if not (data_dir / f"{stem}{companion}").is_file()
            ]
            if missing:
                errors.append(
                    f"{data_dir.relative_to(problem_dir)} 缺少 {companion} companion 文件: "
                    f"{len(missing)}"
                )
    return errors


def _materialize_archived_problem_data(
    problem_dir: Path,
    *,
    force_reextract: bool = False,
    refresh_subpaths: tuple[str, ...] = (),
) -> dict[str, object]:
    """在本次运行快照中安全展开官方 ``data_archives`` 数据包。"""

    archive_dir = problem_dir / "data_archives"
    archives = sorted(archive_dir.glob("*.tar.gz")) if archive_dir.is_dir() else []
    record: dict[str, object] = {
        "archive_count": len(archives),
        "archives": [
            {"name": archive.name, "bytes": archive.stat().st_size}
            for archive in archives
        ],
        "materialized": False,
        "status": "not_packaged",
    }
    if not archives:
        return record

    data_dir = problem_dir / "data"
    if data_dir.is_symlink():
        raise RuntimeError(f"problem/data 不能是符号链接: {data_dir}")
    selective_refresh = bool(refresh_subpaths)
    if data_dir.is_dir() and not force_reextract:
        # 部分上游快照同时保留已展开数据和压缩包。此时沿用已有数据，避免
        # 重复占用数十 GiB；只从本次运行快照中移除多余 archive 硬链接。
        record["status"] = "already_materialized"
    else:
        if selective_refresh and not data_dir.is_dir():
            raise RuntimeError("选择性 archive 刷新要求已有 problem/data 目录")
        if selective_refresh:
            for relative in refresh_subpaths:
                target = problem_dir / relative
                if target.is_symlink() or (target.exists() and not target.is_dir()):
                    raise RuntimeError(f"archive 刷新目标不是普通目录: {target}")
                if target.is_dir():
                    shutil.rmtree(target)
        elif data_dir.exists():
            if not data_dir.is_dir():
                raise RuntimeError(f"problem/data 存在但不是目录: {data_dir}")
            # Hardlinks in a Run are disposable directory entries; removing
            # them does not modify the shared canonical source. This is used
            # only when a public contract proves that an older extraction is
            # stale while the packaged archive is available.
            shutil.rmtree(data_dir)
        for archive_path in archives:
            try:
                # 官方 archive 只来自 NatureBench 的 canonical problem 目录，
                # 使用系统 tar + pigz 避免 Python 单线程 gzip 在 CFS 上成为瓶颈。
                # 禁止恢复 archive 中的宿主 owner/permission，只写入当前 Run。
                subprocess.run(
                    [
                        "tar",
                        "--extract",
                        "--file",
                        str(archive_path),
                        "--directory",
                        str(problem_dir),
                        "--use-compress-program=pigz",
                        "--no-same-owner",
                        "--no-same-permissions",
                        "--keep-directory-symlink",
                    ] + list(refresh_subpaths),
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                # 精简镜像没有 tar/pigz 时保留 Python 安全过滤回退。
                with tarfile.open(archive_path, "r:gz") as archive:
                    if refresh_subpaths:
                        prefixes = tuple(f"{path.rstrip('/')}/" for path in refresh_subpaths)
                        for member in archive:
                            if member.name.startswith(prefixes):
                                archive.extract(member, problem_dir, filter="data")
                    else:
                        archive.extractall(problem_dir, filter="data")
        if not data_dir.is_dir():
            raise RuntimeError(
                "NatureBench data archive 未生成顶层 problem/data 目录"
            )
        record["materialized"] = True
        record["status"] = "extracted"

    shutil.rmtree(archive_dir)
    return record


def _fast_hardlink_tree(source: Path, destination: Path) -> None:
    """用 cp -al 快速复制同一 CFS 上的大型只读 public data 树。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["cp", "-al", str(source), str(destination)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"无法快速 hardlink public data: {source}") from exc


def _ensure_task_context(problem_dir: Path) -> dict[str, str]:
    """为缺失说明文件的上游任务包生成可审计的公开 Judge 上下文。"""

    description = problem_dir / "data_description.md"
    if description.is_file():
        return {"data_description": "source"}
    readme = problem_dir / "README.md"
    if not readme.is_file():
        raise FileNotFoundError(
            f"NatureBench task 同时缺少 README.md 和 data_description.md: {problem_dir}"
        )
    # 官方 Validity Judge 要求两个上下文文件均可读，但个别公开任务包只包含
    # README。fallback 仅复用 Agent 已可见的公开文本，不引入 GT 或评测信息。
    description.write_text(
        "# Dataset Description (Famou staging fallback)\n\n"
        "The upstream task package did not include `problem/data_description.md`. "
        "The canonical public task README is reproduced below so the official "
        "validity judge receives the same public context as the agent.\n\n"
        + readme.read_text(encoding="utf-8", errors="replace"),
        encoding="utf-8",
    )
    return {"data_description": "generated_from_public_readme"}


def _validate_hardlink_source(
    path: Path,
    *,
    agent_uid: int,
    agent_gid: int,
) -> os.stat_result:
    """确认硬链接源对非特权 Agent 不可写，避免 Agent 修改源数据。"""

    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"hardlink source must be a regular file: {path}")
    file_stat = path.stat()
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode & 0o002:
        raise PermissionError(f"hardlink source is world-writable: {path}")
    if file_stat.st_gid == agent_gid and mode & 0o020:
        raise PermissionError(f"hardlink source is writable by Agent group: {path}")
    if file_stat.st_uid == agent_uid and mode & 0o200:
        raise PermissionError(f"hardlink source is writable by Agent owner: {path}")
    return file_stat


def _hardlink_directory(
    source: Path,
    destination: Path,
    *,
    agent_uid: int,
    agent_gid: int,
    collect_metadata: bool = True,
    exclude_top_level: set[str] | None = None,
) -> list[tuple[Path, os.stat_result]]:
    """重建目录树并硬链接普通文件。

    Existing audited snapshots already carry their public manifest.  Callers
    reusing one can disable metadata collection to avoid retaining one Python
    object per file for very large datasets.
    """

    if not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")
    if destination.exists():
        raise FileExistsError(f"run destination already exists: {destination}")
    if source.stat().st_dev != destination.parent.stat().st_dev:
        raise OSError(errno.EXDEV, "hardlink staging requires the same filesystem")

    destination.mkdir()
    linked_files: list[tuple[Path, os.stat_result]] = []
    excluded = set(exclude_top_level or ())
    for current, directories, filenames in os.walk(source, followlinks=False):
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        relative = current_path.relative_to(source)
        if not relative.parts and excluded:
            directories[:] = [name for name in directories if name not in excluded]
        target_current = destination / relative
        for directory_name in directories:
            source_directory = current_path / directory_name
            if source_directory.is_symlink():
                raise RuntimeError(
                    f"hardlink source contains directory symlink: {source_directory}"
                )
            (target_current / directory_name).mkdir()
        for filename in filenames:
            source_file = current_path / filename
            file_stat = _validate_hardlink_source(
                source_file,
                agent_uid=agent_uid,
                agent_gid=agent_gid,
            )
            target_file = target_current / filename
            os.link(source_file, target_file)
            if collect_metadata:
                linked_files.append((target_file.relative_to(destination), file_stat))
    return linked_files


def _set_tree_mode(root: Path, *, directory_mode: int, file_mode: int) -> None:
    """递归设置真实目录和普通文件权限，拒绝把符号链接带入边界。"""

    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"permission tree contains symlink: {path}")
        path.chmod(directory_mode if path.is_dir() else file_mode)


def _set_directory_mode(root: Path, *, directory_mode: int) -> None:
    """只修改新建目录权限，不逐文件触碰硬链接对应的源 inode。"""

    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"permission tree root is not a real directory: {root}")
    root.chmod(directory_mode)
    for current, directories, _filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory_name in directories:
            path = current_path / directory_name
            if path.is_symlink():
                raise RuntimeError(f"permission tree contains symlink: {path}")
            path.chmod(directory_mode)


def _find_forbidden_problem_paths(problem_dir: Path) -> list[Path]:
    """仅按目录项名称检查隐藏数据，避免对海量普通文件逐个 ``stat``。"""

    forbidden_names = {"evaluation", "ground_truth"}
    found: list[Path] = []
    for current, directories, filenames in os.walk(problem_dir, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *filenames):
            if name in forbidden_names:
                found.append(current_path / name)
    return found


def _set_trusted_tree_mode(root: Path, *, shared_problem: Path | None) -> None:
    """隐藏 trusted 树，同时保留共享 problem 文件的源权限。"""

    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            # Trusted task 的 problem 只引用同一 Run 内 Agent 已可见的只读
            # 快照。链接本身位于 root-only trusted/ 下，不会扩大 Agent
            # 权限；避免为包含海量小文件的题面重复创建一整棵硬链接树。
            if shared_problem is not None and path == shared_problem:
                continue
            raise RuntimeError(f"permission tree contains symlink: {path}")
        is_shared_problem = shared_problem is not None and (
            path == shared_problem or shared_problem in path.parents
        )
        if is_shared_problem:
            if path.is_dir():
                path.chmod(0o700)
            continue
        if path.is_dir():
            path.chmod(0o700)
        else:
            # 保留上游已经声明的 owner execute 位；trusted 树对 Agent 始终
            # 是 0700，不会因为 evaluator 工具可执行而扩大读取权限。
            path.chmod(0o700 if path.stat().st_mode & 0o111 else 0o600)


def _repair_trusted_evaluator_executables(evaluation_dir: Path) -> list[str]:
    """恢复上游漏标执行位的 evaluator ELF 或 shebang 工具。"""

    repaired: list[str] = []
    for path in sorted(evaluation_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            prefix = stream.read(4)
        if prefix.startswith(b"#!") or prefix == b"\x7fELF":
            if not path.stat().st_mode & stat.S_IXUSR:
                path.chmod(0o700)
                repaired.append(str(path.relative_to(evaluation_dir)))
    return repaired


def _set_tree_owner(root: Path, *, uid: int, gid: int) -> bool:
    """尝试把 Agent HOME 交给非特权身份，并报告 CFS 是否支持。"""

    if os.geteuid() != 0:
        if os.geteuid() == uid and os.getegid() == gid:
            return True
        raise PermissionError("准备不同 uid 的非特权 Agent HOME 需要 root")
    for path in (root, *root.rglob("*")):
        try:
            os.chown(path, uid, gid, follow_symlinks=False)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.EPERM, errno.EOPNOTSUPP}:
                raise
            # 部分 CFS 禁止容器内 root 改 owner。调用方会只对 Agent 专属目录
            # 开放 other 权限；trusted/ 仍保持 root 0700，不受该回退影响。
            return False
    return True


def _public_manifest(
    problem_dir: Path,
    *,
    hash_max_file_bytes: int | None = None,
    hash_total_budget_bytes: int | None = None,
    known_files: list[tuple[Path, os.stat_result]] | None = None,
) -> dict[str, object]:
    """生成公开题面清单，并按预算计算文件 SHA-256。"""

    files: list[dict[str, object]] = []
    remaining_hash_budget = hash_total_budget_bytes
    if known_files is None:
        file_records = [
            (path.relative_to(problem_dir), path.stat())
            for path in sorted(problem_dir.rglob("*"))
            if path.is_file()
        ]
    else:
        # _hardlink_directory 已按目录名和文件名排序，且 stat 来自同一 inode；
        # 直接复用，避免对十万级小文件再执行一次 CFS 元数据扫描。
        file_records = known_files
    for relative_path, file_stat in file_records:
        path = problem_dir / relative_path
        should_hash = (
            (hash_max_file_bytes is None or file_stat.st_size <= hash_max_file_bytes)
            and (
                remaining_hash_budget is None
                or file_stat.st_size <= remaining_hash_budget
            )
        )
        sha256: str | None = None
        hash_status = "skipped_budget"
        if should_hash:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
            hash_status = "hashed"
            if remaining_hash_budget is not None:
                remaining_hash_budget -= file_stat.st_size
        elif hash_max_file_bytes is not None and file_stat.st_size > hash_max_file_bytes:
            hash_status = "skipped_file_size"
        files.append(
            {
                "path": str(relative_path),
                "size": file_stat.st_size,
                "mtime_ns": file_stat.st_mtime_ns,
                "device": file_stat.st_dev,
                "inode": file_stat.st_ino,
                "sha256": sha256,
                "hash_status": hash_status,
            }
        )
    return {
        "problem_dir": "problem",
        "hash_policy": {
            "max_file_bytes": hash_max_file_bytes,
            "total_budget_bytes": hash_total_budget_bytes,
        },
        "files": files,
    }


def _filtered_settings_env(
    source: Path,
    *,
    names: set[str],
    prefixes: tuple[str, ...],
) -> dict[str, str]:
    """从设置文件提取指定白名单中的字符串环境变量。"""
    raw = json.loads(source.read_text(encoding="utf-8"))
    source_env = raw.get("env") if isinstance(raw, dict) else None
    if not isinstance(source_env, dict):
        raise ValueError(f"Claude settings contains no env mapping: {source}")
    allowed_env = {
        str(key): str(value)
        for key, value in source_env.items()
        if isinstance(key, str)
        and isinstance(value, str)
        and (key in names or key.startswith(prefixes))
    }
    if not allowed_env:
        raise ValueError(f"Claude settings contains no supported credentials: {source}")
    return allowed_env


def _write_settings(destination: Path, allowed_env: dict[str, str]) -> None:
    """以仅属主可读写权限写出不含 hooks 的设置文件。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"env": allowed_env}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    destination.chmod(0o600)


def _stage_claude_settings(
    source: Path,
    run_dir: Path,
    *,
    agent_uid: int,
    agent_gid: int,
) -> None:
    """仅暂存 Claude CLI 所需环境项，不复制 Judge 专属配置。"""
    del agent_uid, agent_gid
    allowed_env = _filtered_settings_env(
        source,
        names=_ALLOWED_CLAUDE_ENV_NAMES,
        prefixes=_ALLOWED_CLAUDE_ENV_PREFIXES,
    )
    _write_settings(
        run_dir / "agent_home" / ".claude" / "settings.json",
        allowed_env,
    )


def _stage_kimi_code_config(source: Path, run_dir: Path) -> None:
    """Stage Kimi provider/model config into the Agent-only HOME."""
    destination = run_dir / "agent_home" / ".kimi-code" / "config.toml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o600)


def _stage_judge_settings(source: Path, destination: Path) -> None:
    """把 Judge 凭据写到 Agent 挂载根之外的可信目录。"""
    allowed_env = _filtered_settings_env(
        source,
        names=set(),
        prefixes=_ALLOWED_JUDGE_ENV_PREFIXES,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    _write_settings(destination, allowed_env)


def prepare_run(
    *,
    naturebench_root: Path,
    task_id: str,
    famou_source: Path,
    run_dir: Path,
    claude_settings: Path | None = None,
    kimi_code_config: Path | None = None,
    judge_settings_source: Path | None = None,
    trusted_judge_settings: Path | None = None,
    agent_uid: int = 10001,
    agent_gid: int = 10001,
    problem_staging_mode: str = "copy",
    problem_snapshot_source: Path | None = None,
    problem_snapshot_manifest: Path | None = None,
    problem_snapshot_link: bool = False,
    manifest_hash_max_file_bytes: int | None = None,
    manifest_hash_total_budget_bytes: int | None = None,
) -> None:
    """创建公开工作区与 root-only trusted/ 并存的任务运行树。"""
    task_dir = naturebench_root / "data" / "naturebench_data" / "tasks" / task_id
    public_problem = task_dir / "problem"
    if not (task_dir / "evaluation").is_dir():
        raise FileNotFoundError(f"NatureBench task evaluator not found: {task_dir}")
    if problem_staging_mode not in {"auto", "copy", "hardlink"}:
        raise ValueError(f"unsupported problem staging mode: {problem_staging_mode}")
    if (problem_snapshot_source is None) != (problem_snapshot_manifest is None):
        raise ValueError("problem snapshot source 和 manifest 必须同时提供")
    if problem_snapshot_link and problem_snapshot_source is None:
        raise ValueError("problem snapshot link 需要同时提供 snapshot source 和 manifest")

    # auto 只在源数据与 run 根目录位于同一文件系统时启用硬链接。
    # 这让小任务继续兼容独立复制，也允许数百 GiB 的公开数据零拷贝接入。
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    selected_staging_mode = problem_staging_mode
    snapshot_manifest: Path | None = None
    snapshot_refresh: dict[str, object] | None = None
    force_archive_reextract = False
    if problem_snapshot_source is not None:
        snapshot_source = problem_snapshot_source.expanduser().resolve()
        snapshot_manifest = problem_snapshot_manifest.expanduser().resolve()
        _validate_problem_snapshot(
            snapshot_source,
            snapshot_manifest,
            agent_uid=agent_uid,
            agent_gid=agent_gid,
        )
        snapshot_errors = _public_contract_errors(task_id, snapshot_source)
        if snapshot_errors:
            # A rerun must never silently inherit a stale public snapshot. Fall
            # back to the canonical task package and materialize it normally;
            # the post-materialization check below remains the final gate.
            public_problem = task_dir / "problem"
            snapshot_refresh = {
                "refreshed": True,
                "reason": "stale_public_snapshot",
                "snapshot_source": str(snapshot_source),
                "snapshot_manifest": str(snapshot_manifest),
                "snapshot_errors": snapshot_errors,
                "canonical_source": str(public_problem),
            }
            snapshot_manifest = None
            selected_staging_mode = problem_staging_mode
            force_archive_reextract = True
        else:
            public_problem = snapshot_source
            selected_staging_mode = (
                "snapshot_link" if problem_snapshot_link else "snapshot_hardlink"
            )
    if selected_staging_mode == "auto":
        selected_staging_mode = (
            "hardlink"
            if public_problem.stat().st_dev == run_dir.parent.stat().st_dev
            else "copy"
        )
    if not force_archive_reextract and _public_contract_errors(
        task_id, public_problem
    ):
        # The canonical source may retain an older extracted data directory
        # alongside a newer archive. Rebuild only the new Run's data tree.
        force_archive_reextract = (public_problem / "data_archives").is_dir()
    archive_refresh_subpaths = (
        ("data/band_gap/test",)
        if task_id == "s42256-023-00628-2" and force_archive_reextract
        else ()
    )

    run_dir.mkdir(parents=True, exist_ok=False)
    linked_problem_files: list[tuple[Path, os.stat_result]] | None = None
    if selected_staging_mode == "snapshot_link":
        (run_dir / "problem").symlink_to(
            os.path.relpath(public_problem, start=run_dir),
            target_is_directory=True,
        )
    elif selected_staging_mode == "snapshot_hardlink":
        # fm-job 只挂载当前 Run。软链到历史 Run 会迫使容器扩大挂载边界，
        # 间接暴露其他实验目录。这里复用已校验文件的 inode，同时为新 Run
        # 建立独立目录树，既避免复制大数据，也保持单 Run 隔离。
        linked_problem_files = _hardlink_directory(
            public_problem,
            run_dir / "problem",
            agent_uid=agent_uid,
            agent_gid=agent_gid,
            collect_metadata=False,
            exclude_top_level={"data"} if force_archive_reextract else None,
        )
    elif selected_staging_mode == "hardlink":
        linked_problem_files = _hardlink_directory(
            public_problem,
            run_dir / "problem",
            agent_uid=agent_uid,
            agent_gid=agent_gid,
            exclude_top_level={"data"} if force_archive_reextract else None,
        )
    else:
        _copy_directory(
            public_problem,
            run_dir / "problem",
            exclude_top_level={"data"} if force_archive_reextract else None,
        )
    if archive_refresh_subpaths:
        _fast_hardlink_tree(
            public_problem / "data",
            run_dir / "problem" / "data",
        )
    archive_materialization = (
        {
            "archive_count": 0,
            "archives": [],
            "materialized": False,
            "status": "shared_audited_snapshot",
        }
        if selected_staging_mode in {"snapshot_hardlink", "snapshot_link"}
        else _materialize_archived_problem_data(
            run_dir / "problem",
            force_reextract=force_archive_reextract,
            refresh_subpaths=archive_refresh_subpaths,
        )
    )
    public_contract_errors = _public_contract_errors(task_id, run_dir / "problem")
    if public_contract_errors:
        raise RuntimeError(
            "公开任务数据契约不满足，禁止启动 Agent: "
            + "; ".join(public_contract_errors)
        )
    task_context = _ensure_task_context(run_dir / "problem")
    if linked_problem_files is not None:
        if selected_staging_mode == "snapshot_link":
            linked_problem_files = None
        elif archive_materialization["status"] == "extracted":
            # 解压生成了硬链接阶段不存在的新文件，必须回退到完整扫描。
            linked_problem_files = None
        else:
            # data 已存在时，_materialize_archived_problem_data 会删除冗余
            # data_archives；这些已删除条目不能进入最终公开清单。
            linked_problem_files = [
                record
                for record in linked_problem_files
                if not record[0].parts or record[0].parts[0] != "data_archives"
            ]
            if task_context["data_description"] == "generated_from_public_readme":
                generated_description = run_dir / "problem/data_description.md"
                linked_problem_files.append(
                    (
                        Path("data_description.md"),
                        generated_description.stat(),
                    )
                )
                linked_problem_files.sort(key=lambda record: str(record[0]))
    runtime_root = run_dir / "famou-scientist"
    runtime_root.mkdir()
    _copy_directory(
        famou_source / "famou_scientist",
        runtime_root / "famou_scientist",
        repository=True,
    )
    trusted_root = run_dir / "trusted"
    trusted_runtime = trusted_root / "famou-scientist" / "famou_scientist"
    trusted_runtime.parent.mkdir(parents=True)
    _copy_trusted_runtime(famou_source / "famou_scientist", trusted_runtime)
    trusted_naturebench = trusted_root / "naturebench"
    trusted_naturebench.mkdir(parents=True)
    for filename in ("eval_service.py", "_evaluator_runner.py"):
        source = naturebench_root / filename
        if not source.is_file():
            raise FileNotFoundError(f"NatureBench trusted runtime file missing: {source}")
        shutil.copy2(source, trusted_naturebench / filename)
    # 官方 Validity Judge 依赖 judge_core 和 agent 注册表。它们只进入
    # root-only trusted/，不会进入 Agent 可见的 famou-scientist 快照。
    for directory_name in ("judge_core", "agent"):
        source = naturebench_root / directory_name
        if source.is_dir():
            _copy_directory(source, trusted_naturebench / directory_name)
    trusted_task = (
        trusted_naturebench
        / "data"
        / "naturebench_data"
        / "tasks"
        / task_id
    )
    # Trusted Evaluator/Judge 与 Agent 必须看到完全相同的公开数据快照。
    # task 私有部分照常复制；problem 从 root-only trusted/ 内引用本 Run 的
    # 只读公开快照，避免对十万级小文件再执行一次完整硬链接遍历。
    _copy_task_without_problem(task_dir, trusted_task)
    trusted_shared_problem = trusted_task / "problem"
    trusted_shared_problem.symlink_to(
        os.path.relpath(run_dir / "problem", start=trusted_task),
        target_is_directory=True,
    )
    for relative in (
        "agent_home",
        "agent_control",
        "workspace",
        "controller/evaluator_channel/requests",
        "controller/evaluator_channel/responses",
        "results",
    ):
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    if claude_settings is not None:
        if not claude_settings.is_file():
            raise FileNotFoundError(f"Claude settings not found: {claude_settings}")
        _stage_claude_settings(
            claude_settings,
            run_dir,
            agent_uid=agent_uid,
            agent_gid=agent_gid,
        )
    if kimi_code_config is not None:
        if not kimi_code_config.is_file():
            raise FileNotFoundError(f"Kimi Code config not found: {kimi_code_config}")
        _stage_kimi_code_config(kimi_code_config, run_dir)
    if trusted_judge_settings is not None:
        source = judge_settings_source or claude_settings
        if source is None or not source.is_file():
            raise FileNotFoundError(
                "trusted Judge 配置需要有效的设置来源"
            )
        try:
            trusted_judge_settings.resolve().relative_to(trusted_root.resolve())
        except ValueError as exc:
            raise ValueError("Judge 配置必须位于本次 run 的 trusted/ 内") from exc
        _stage_judge_settings(source, trusted_judge_settings)
    # Claude、Codex 和 OpenCode 都使用同一个非特权 HOME。即使没有 Claude
    # settings，也必须提前创建并移交目录，避免 Agent 首次写缓存时权限失败。
    agent_home = run_dir / "agent_home"
    owner_isolated = _set_tree_owner(agent_home, uid=agent_uid, gid=agent_gid)
    _set_tree_mode(
        agent_home,
        # CFS 不支持 chown 时只开放 Agent 专属 HOME；同一 Task Job 内所有
        # 非特权节点属于同一信任域，可信目录仍由 root 权限隔离。
        directory_mode=0o700 if owner_isolated else 0o707,
        file_mode=0o600 if owner_isolated else 0o606,
    )
    public_manifest_path = run_dir / "controller" / "public_problem_manifest.json"
    if selected_staging_mode in {"snapshot_hardlink", "snapshot_link"}:
        shutil.copy2(snapshot_manifest, public_manifest_path)
    else:
        public_manifest_path.write_text(
            json.dumps(
                _public_manifest(
                    run_dir / "problem",
                    hash_max_file_bytes=manifest_hash_max_file_bytes,
                    hash_total_budget_bytes=manifest_hash_total_budget_bytes,
                    known_files=linked_problem_files,
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    (run_dir / "controller" / "staging.json").write_text(
        json.dumps(
            {
                "problem_staging_mode": selected_staging_mode,
                "requested_problem_staging_mode": problem_staging_mode,
                "manifest_hash_max_file_bytes": manifest_hash_max_file_bytes,
                "manifest_hash_total_budget_bytes": manifest_hash_total_budget_bytes,
                "archive_materialization": archive_materialization,
                "task_context": task_context,
                "trusted_problem_mode": "symlink_to_public_snapshot",
                "problem_snapshot_source": (
                    str(public_problem)
                    if selected_staging_mode in {"snapshot_hardlink", "snapshot_link"}
                    else None
                ),
                "problem_snapshot_manifest": (
                    str(snapshot_manifest)
                    if selected_staging_mode in {"snapshot_hardlink", "snapshot_link"}
                    else None
                ),
                "snapshot_refresh": snapshot_refresh,
                "public_contract": {
                    "status": "passed",
                    "errors": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    forbidden = (
        []
        if selected_staging_mode in {"snapshot_hardlink", "snapshot_link"}
        else _find_forbidden_problem_paths(run_dir / "problem")
    )
    if forbidden:
        raise RuntimeError(f"hidden evaluator data entered Agent run directory: {forbidden}")
    # 同一个 fm-job 共享资源，但隐藏数据和可信代码只允许 Supervisor/Evaluator
    # 身份读取。Agent 即使知道路径也只能得到 Permission denied。
    _set_trusted_tree_mode(trusted_root, shared_problem=trusted_shared_problem)
    repaired_executables = _repair_trusted_evaluator_executables(
        trusted_task / "evaluation"
    )
    if repaired_executables:
        staging_path = run_dir / "controller" / "staging.json"
        staging = json.loads(staging_path.read_text(encoding="utf-8"))
        staging["repaired_trusted_evaluator_executables"] = repaired_executables
        staging_path.write_text(
            json.dumps(staging, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (run_dir / "controller").chmod(0o700)
    # Agent 只从该目录读取 Controller 的截止信号；目录不可由非特权 UID 写入。
    (run_dir / "agent_control").chmod(0o755)
    if selected_staging_mode == "snapshot_link":
        # The source snapshot was validated before linking and remains outside
        # the Agent-writable tree. Do not follow/chmod the symlink here.
        pass
    elif selected_staging_mode in {"hardlink", "snapshot_hardlink"}:
        # 硬链接文件保持 NatureBench 源 inode 的 root-owned 只读权限；这里只
        # 收紧新建目录，避免 chmod 通过共享 inode 修改源数据权限。
        _set_directory_mode(run_dir / "problem", directory_mode=0o555)
    else:
        _set_tree_mode(run_dir / "problem", directory_mode=0o555, file_mode=0o444)


def _build_parser() -> argparse.ArgumentParser:
    """构建运行目录准备命令的参数解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--naturebench-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--famou-source", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--claude-settings")
    parser.add_argument("--kimi-code-config")
    parser.add_argument("--judge-settings-source")
    parser.add_argument("--trusted-judge-settings")
    parser.add_argument("--agent-uid", type=int, default=10001)
    parser.add_argument("--agent-gid", type=int, default=10001)
    parser.add_argument(
        "--problem-staging-mode",
        choices=("auto", "copy", "hardlink"),
        default="copy",
    )
    parser.add_argument("--problem-snapshot-source")
    parser.add_argument("--problem-snapshot-manifest")
    parser.add_argument("--problem-snapshot-link", action="store_true")
    parser.add_argument("--manifest-hash-max-file-bytes", type=int)
    parser.add_argument("--manifest-hash-total-budget-bytes", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行运行目录准备命令。"""
    args = _build_parser().parse_args(list(argv or sys.argv[1:]))
    prepare_run(
        naturebench_root=Path(args.naturebench_root).expanduser().resolve(),
        task_id=args.task_id,
        famou_source=Path(args.famou_source).expanduser().resolve(),
        run_dir=Path(args.run_dir).expanduser().resolve(),
        claude_settings=(
            Path(args.claude_settings).expanduser().resolve()
            if args.claude_settings
            else None
        ),
        kimi_code_config=(
            Path(args.kimi_code_config).expanduser().resolve()
            if args.kimi_code_config
            else None
        ),
        judge_settings_source=(
            Path(args.judge_settings_source).expanduser().resolve()
            if args.judge_settings_source
            else None
        ),
        trusted_judge_settings=(
            Path(args.trusted_judge_settings).expanduser().resolve()
            if args.trusted_judge_settings
            else None
        ),
        agent_uid=args.agent_uid,
        agent_gid=args.agent_gid,
        problem_staging_mode=args.problem_staging_mode,
        problem_snapshot_source=(
            Path(args.problem_snapshot_source)
            if args.problem_snapshot_source
            else None
        ),
        problem_snapshot_manifest=(
            Path(args.problem_snapshot_manifest)
            if args.problem_snapshot_manifest
            else None
        ),
        problem_snapshot_link=args.problem_snapshot_link,
        manifest_hash_max_file_bytes=args.manifest_hash_max_file_bytes,
        manifest_hash_total_budget_bytes=args.manifest_hash_total_budget_bytes,
    )
    print(Path(args.run_dir).expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
