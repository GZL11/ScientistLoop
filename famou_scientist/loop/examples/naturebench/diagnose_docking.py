#!/usr/bin/env python3
"""在可信环境中诊断 NatureBench 分子 docking 的各个执行阶段。"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Any


def _package_version(name: str) -> str | None:
    """读取依赖版本；缺失依赖返回空值。"""

    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _load_input(
    task_dir: Path,
    submission_dir: Path,
    pocket_id: str,
    molecule_index: int,
) -> tuple[str, list[float]]:
    """读取指定 pocket 的分子和官方 pocket 中心。"""

    prediction_path = submission_dir / "crossdock" / "generated_molecules.json"
    predictions = json.loads(prediction_path.read_text(encoding="utf-8"))
    molecules = predictions[pocket_id]
    smiles = str(molecules[molecule_index])

    index_path = (
        task_dir
        / "evaluation"
        / "ground_truth"
        / "crossdock"
        / "pocket_index.json"
    )
    entries = json.loads(index_path.read_text(encoding="utf-8"))
    centers = {str(item["pocket_id"]): item["center_of_mass"] for item in entries}
    center = [float(value) for value in centers[pocket_id]]
    return smiles, center


def _parse_affinity(stdout: str) -> float | None:
    """按官方 evaluator 的规则解析第一名 docking affinity。"""

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("1"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        if math.isfinite(value):
            return value
    return None


def diagnose(
    *,
    task_dir: Path,
    submission_dir: Path,
    pocket_id: str,
    molecule_index: int,
    timeout_sec: float,
) -> dict[str, Any]:
    """执行一次 ligand 准备和 QuickVina，并返回完整公开诊断。"""

    result: dict[str, Any] = {
        "valid": False,
        "stage": "initialization",
        "task_dir": str(task_dir),
        "submission_dir": str(submission_dir),
        "pocket_id": pocket_id,
        "molecule_index": molecule_index,
        "dependency_versions": {
            name: _package_version(name) for name in ("meeko", "rdkit", "numpy")
        },
    }
    try:
        from meeko import MoleculePreparation, PDBQTWriterLegacy
        from rdkit import Chem
        from rdkit.Chem import AllChem

        smiles, center = _load_input(
            task_dir,
            submission_dir,
            pocket_id,
            molecule_index,
        )
        result["smiles"] = smiles
        result["pocket_center"] = center

        result["stage"] = "rdkit_conformer"
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            raise ValueError("RDKit 无法解析 SMILES")
        molecule = Chem.AddHs(molecule)
        embed_rc = int(AllChem.EmbedMolecule(molecule, randomSeed=42, maxAttempts=50))
        result["embed_returncode"] = embed_rc
        if embed_rc == -1:
            raise RuntimeError("RDKit 无法生成三维构象")
        try:
            result["uff_returncode"] = int(
                AllChem.UFFOptimizeMolecule(molecule, maxIters=200)
            )
        except Exception as exc:  # noqa: BLE001 - UFF 失败时官方逻辑继续执行
            result["uff_error"] = repr(exc)

        result["stage"] = "meeko_ligand_preparation"
        setups = MoleculePreparation().prepare(molecule)
        result["molecule_setup_count"] = len(setups)
        if not setups:
            raise RuntimeError("Meeko 未生成 molecule setup")

        receptor = (
            task_dir
            / "evaluation"
            / "ground_truth"
            / "crossdock"
            / "receptor_data"
            / pocket_id
            / "receptor_pocket.pdbqt"
        )
        qvina = task_dir / "evaluation" / "qvina02"
        if not qvina.exists():
            resolved = shutil.which("qvina02")
            if not resolved:
                raise FileNotFoundError("官方 task 和 PATH 中都不存在 qvina02")
            qvina = Path(resolved)
        result["receptor"] = {
            "path": str(receptor),
            "exists": receptor.is_file(),
            "readable": os.access(receptor, os.R_OK),
            "size_bytes": receptor.stat().st_size if receptor.is_file() else None,
        }
        result["qvina"] = {
            "path": str(qvina),
            "exists": qvina.is_file(),
            "executable": os.access(qvina, os.X_OK),
        }
        if not receptor.is_file():
            raise FileNotFoundError(f"receptor 不存在: {receptor}")
        if not os.access(qvina, os.X_OK):
            raise PermissionError(f"qvina02 不可执行: {qvina}")

        with tempfile.TemporaryDirectory(prefix="famou-nb-docking-") as tmp:
            temporary_dir = Path(tmp)
            ligand = temporary_dir / "ligand.pdbqt"
            output = temporary_dir / "out.pdbqt"
            writer_errors: list[str] = []
            for setup in setups:
                pdbqt, is_ok, error = PDBQTWriterLegacy.write_string(setup)
                if is_ok:
                    ligand.write_text(pdbqt, encoding="utf-8")
                    break
                writer_errors.append(str(error))
            else:
                raise RuntimeError(f"Meeko 无法写出 ligand PDBQT: {writer_errors}")
            result["ligand_size_bytes"] = ligand.stat().st_size

            cx, cy, cz = center
            command = [
                str(qvina),
                "--receptor",
                str(receptor),
                "--ligand",
                str(ligand),
                "--center_x",
                f"{cx:.4f}",
                "--center_y",
                f"{cy:.4f}",
                "--center_z",
                f"{cz:.4f}",
                "--size_x",
                "20",
                "--size_y",
                "20",
                "--size_z",
                "20",
                "--out",
                str(output),
                "--exhaustiveness",
                "16",
                "--num_modes",
                "1",
                "--cpu",
                "1",
            ]
            result["stage"] = "qvina"
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(1.0, timeout_sec),
                check=False,
            )
            affinity = _parse_affinity(process.stdout)
            result.update(
                {
                    "qvina_returncode": process.returncode,
                    "qvina_stdout": process.stdout,
                    "qvina_stderr": process.stderr,
                    "output_exists": output.is_file(),
                    "output_size_bytes": output.stat().st_size if output.is_file() else None,
                    "affinity": affinity,
                }
            )
            if process.returncode != 0:
                raise RuntimeError(f"qvina02 返回非零状态: {process.returncode}")
            if affinity is None:
                raise RuntimeError("qvina02 stdout 中没有可解析的 affinity")

        result["stage"] = "completed"
        result["valid"] = True
    except Exception as exc:  # noqa: BLE001 - 诊断工具必须保留被官方代码吞掉的异常
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    return result


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--submission-dir", required=True)
    parser.add_argument("--pocket-id", default="pocket_000")
    parser.add_argument("--molecule-index", type=int, default=0)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行诊断并用退出码表示 docking 是否成功。"""

    args = _build_parser().parse_args(argv)
    result = diagnose(
        task_dir=Path(args.task_dir).expanduser().resolve(),
        submission_dir=Path(args.submission_dir).expanduser().resolve(),
        pocket_id=str(args.pocket_id),
        molecule_index=int(args.molecule_index),
        timeout_sec=float(args.timeout_sec),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
