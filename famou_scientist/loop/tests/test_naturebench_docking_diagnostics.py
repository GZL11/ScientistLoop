"""测试 NatureBench docking 可信诊断工具。"""

from famou_scientist.loop.examples.naturebench.diagnose_docking import (
    _parse_affinity,
)


def test_parse_affinity_reads_quickvina_ranking_row() -> None:
    """应从 QuickVina 排名表中读取第一名 affinity。"""

    stdout = """mode | affinity | dist from best mode
-----+----------+--------------------
   1       -9.3      0.000      0.000
"""

    assert _parse_affinity(stdout) == -9.3


def test_parse_affinity_rejects_unrelated_numbered_output() -> None:
    """不完整或非数值排名行不能伪造成有效 affinity。"""

    assert _parse_affinity("100% complete\n1 invalid\n") is None
