"""
runners/cli/run_b3.py — B3 端到端评测（薄封装，实际逻辑在 run_bench.py）

等价于: python -m runners.cli.run_bench --benchmark b3 ...
"""
import sys

sys.argv.insert(1, "--benchmark")
sys.argv.insert(2, "b3")

from .run_bench import main

if __name__ == "__main__":
    main()
