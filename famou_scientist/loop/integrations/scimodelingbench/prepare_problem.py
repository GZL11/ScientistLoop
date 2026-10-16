"""Trusted public-problem exporter for SciModelingBench tasks."""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .evaluator_worker import _load_task
from .task_catalog import DEFAULT_HF_REVISION, SciModelingBenchTaskSpec, task_spec


def prepare_task_problem(
    *,
    task_id: str,
    problem_dir: str | Path,
    revision: str | None = None,
    cache_dir: str | Path | None = None,
    task_loader: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Materialize the Agent-visible SciModelingBench task bundle.

    This function is trusted setup code.  It may load the package Task and HF
    cache, but it writes only ``Task.build_input()`` outputs and public task
    contracts to ``problem_dir``.
    """

    spec = task_spec(task_id)
    selected_revision = revision or DEFAULT_HF_REVISION
    destination = Path(problem_dir).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"problem directory is not empty: {destination}; pass overwrite=True"
            )
        shutil.rmtree(destination)
    data_dir = destination / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    task = _load_task(
        spec.task_id,
        revision=selected_revision,
        loader=task_loader,
        cache_dir=cache_dir,
    )
    bundle = task.build_input()
    manifest = _jsonable(bundle.manifest)
    views = tuple(manifest.get("views") or ())
    tables = _export_views(bundle.data, views, data_dir)
    metric_contract = _metric_contract(spec, task)
    submission_schema = _submission_schema(spec, views)

    _write_json(destination / "manifest.json", manifest)
    _write_json(destination / "metric_contract.json", metric_contract)
    _write_json(destination / "submission_schema.json", submission_schema)
    _write_json(destination / "tables.json", {"tables": tables})
    _write_json(destination / "context.json", {"context": manifest.get("context") or []})
    _write_task_markdown(destination / "task.md", spec, manifest, tables)

    result = {
        "task_id": spec.task_id,
        "problem_dir": str(destination),
        "revision": selected_revision,
        "cache_dir": str(Path(cache_dir).expanduser().resolve()) if cache_dir else None,
        "views": [
            {
                "name": table["name"],
                "role": table["role"],
                "rows": table["rows"],
                "file": table["file"],
            }
            for table in tables
        ],
        "submission_size": spec.submission_size,
        "primary_metric": spec.primary_metric,
    }
    _write_json(destination / "prepare_report.json", result)
    return result


def _export_views(data: Any, views: Sequence[Mapping[str, Any]], data_dir: Path) -> list[dict[str, Any]]:
    """Export each manifest view to JSONL from the corresponding public object."""

    exported: list[dict[str, Any]] = []
    for view in views:
        name = str(view["name"])
        table = _table_for_view(data, name, len(views))
        path = data_dir / f"{_safe_name(name)}.jsonl"
        rows = _write_jsonl(path, table)
        exported.append(
            {
                "name": name,
                "role": view.get("role"),
                "description": view.get("description"),
                "rows": rows,
                "file": f"data/{path.name}",
                "format": "jsonl",
                "fields": view.get("fields") or [],
            }
        )
    return exported


def _table_for_view(data: Any, view_name: str, view_count: int) -> Any:
    if view_count == 1 and _looks_like_table(data):
        return data
    if hasattr(data, view_name):
        return getattr(data, view_name)
    if isinstance(data, Mapping) and view_name in data:
        return data[view_name]
    raise KeyError(f"AgentInputBundle.data has no public table for view {view_name!r}")


def _looks_like_table(value: Any) -> bool:
    return hasattr(value, "__iter__") and (
        hasattr(value, "column_names") or hasattr(value, "columns")
    )


def _write_jsonl(path: Path, table: Any) -> int:
    rows = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in _iter_rows(table):
            handle.write(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            rows += 1
    return rows


def _iter_rows(table: Any):
    if hasattr(table, "to_dict") and hasattr(table, "columns"):
        records = table.to_dict(orient="records")
        yield from records
        return
    if isinstance(table, Mapping):
        keys = list(table)
        values = [table[key] for key in keys]
        for items in zip(*values, strict=True):
            yield dict(zip(keys, items, strict=True))
        return
    for row in table:
        yield row


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return str(value)


def _metric_contract(spec: SciModelingBenchTaskSpec, task: Any) -> dict[str, Any]:
    directions = getattr(task, "metric_directions", {}) or {}
    return {
        "benchmark": f"scimodelingbench/{spec.task_id}",
        "primary_metric": getattr(task, "primary_metric", spec.primary_metric),
        "direction": directions.get(spec.primary_metric, spec.direction),
        "submission_size": getattr(task, "submission_size", spec.submission_size),
        "exact_submission_size": spec.exact_submission_size,
        "summary_size": getattr(task, "summary_size", spec.summary_size),
        "task_form": spec.task_form,
        "official_evaluator": "trusted_only",
        "agent_feedback": (
            "Only aggregate scalar metrics are returned. Hidden labels, objective "
            "outputs, per-candidate scores, and full evaluator state are redacted."
        ),
    }


def _submission_schema(
    spec: SciModelingBenchTaskSpec,
    views: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_view = _candidate_schema_view(spec, views)
    fields = [
        field
        for field in candidate_view.get("fields", [])
        if isinstance(field, Mapping) and field.get("role") != "target"
    ]
    properties = {
        str(field["name"]): _json_schema_type(str(field.get("physical_type", "")))
        for field in fields
        if field.get("name")
    }
    required = [
        str(field["name"])
        for field in fields
        if field.get("required", True) and field.get("name")
    ]
    item_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": True,
        "properties": properties,
    }
    if required:
        item_schema["required"] = required
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"SciModelingBench {spec.task_id} submission",
        "type": "array",
        "items": item_schema,
        "minItems": spec.submission_size,
        "description": (
            "Write this JSON array to OUTPUT_DIR/submission.json. For ranking "
            "tasks, submit candidates from data/candidates.jsonl in desired order."
        ),
    }
    if spec.exact_submission_size:
        schema["maxItems"] = spec.submission_size
    return schema


def _candidate_schema_view(
    spec: SciModelingBenchTaskSpec,
    views: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if spec.task_form == "candidate-pool ranking":
        for view in views:
            if view.get("role") == "candidates":
                return view
    for view in views:
        if view.get("role") == "observations":
            return view
    return views[0] if views else {"fields": []}


def _json_schema_type(physical_type: str) -> dict[str, Any]:
    lower = physical_type.lower()
    if any(token in lower for token in ("int", "float", "double", "number")):
        return {"type": ["number", "integer"]}
    if "bool" in lower:
        return {"type": "boolean"}
    if any(token in lower for token in ("list", "sequence", "[")):
        return {"type": "array"}
    return {"type": "string"}


def _write_task_markdown(
    path: Path,
    spec: SciModelingBenchTaskSpec,
    manifest: Mapping[str, Any],
    tables: Sequence[Mapping[str, Any]],
) -> None:
    lines = [
        f"# SciModelingBench: {spec.task_id}",
        "",
        f"- Domain: {spec.domain}",
        f"- Task form: {spec.task_form}",
        f"- Primary metric: {spec.primary_metric}",
        f"- Submission size: {spec.submission_size}",
        f"- Dataset snapshot: {manifest.get('repo_id')} @ {manifest.get('resolved_revision')}",
        "",
        "## Public Data",
        "",
    ]
    for table in tables:
        lines.append(
            f"- `{table['file']}`: `{table['name']}` / {table['role']} / {table['rows']} rows"
        )
    lines.extend(
        [
            "",
            "## Submission",
            "",
            "Create `run.py` that reads `BENCHMARK_TASK_DIR` or `DATA_DIR` and writes "
            "`OUTPUT_DIR/submission.json` as a JSON array.",
            "",
            "Official scoring is only run by the trusted evaluator. The public problem "
            "directory intentionally excludes hidden labels, objective outputs, and "
            "the evaluator cache.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_jsonable(value), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--problem-dir", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--task-loader")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = prepare_task_problem(
        task_id=args.task_id,
        problem_dir=args.problem_dir,
        revision=args.revision,
        cache_dir=args.cache_dir,
        task_loader=args.task_loader,
        overwrite=args.overwrite,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["prepare_task_problem"]
