"""
runners/cli/run_b2.py — B2 澄清阶段评测（薄封装，实际逻辑在 run_bench.py）

等价于: python -m runners.cli.run_bench --benchmark b2 ...
"""
import sys

sys.argv.insert(1, "--benchmark")
sys.argv.insert(2, "b2")

from .run_bench import main

if __name__ == "__main__":
    main()
