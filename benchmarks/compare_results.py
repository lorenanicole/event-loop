#!/usr/bin/env python3
"""
Compare benchmark results between Python 3.14 and 3.15
"""

import json
import sys
from pathlib import Path


def load_results(version: str) -> dict:
    """Load benchmark results for a version."""
    results_dir = Path(__file__).parent / "results"
    file = results_dir / f"benchmark_py{version}.json"

    if not file.exists():
        return None

    with open(file) as f:
        return json.load(f)


def compare_results(py314: dict, py315: dict) -> None:
    """Compare results and show improvements."""

    benchmarks_314 = {b["name"]: b for b in py314["benchmarks"]}
    benchmarks_315 = {b["name"]: b for b in py315["benchmarks"]}

    total_improvement = 0
    improvements = []

    for name in sorted(benchmarks_314.keys()):
        b314 = benchmarks_314[name]
        b315 = benchmarks_315.get(name)

        if not b315:
            continue

        time_314 = b314["duration_ms"]
        time_315 = b315["duration_ms"]

        # Calculate change percentage
        change_pct = ((time_314 - time_315) / time_314) * 100
        total_improvement += change_pct

        if change_pct > 0:
            improvements.append((name, change_pct))
        elif change_pct < 0:
            f"✗ Slower {abs(change_pct):.1f}%"
        else:
            pass

    avg_improvement = total_improvement / len(benchmarks_314)

    if improvements:
        for name, _pct in sorted(improvements, key=lambda x: x[1], reverse=True):
            pass

    # Insights

    json_improvement = next((p for n, p in improvements if n == "json_operations"), 0)
    async_improvement = next((p for n, p in improvements if n == "async_operations"), 0)

    if json_improvement > 5:
        pass
    if async_improvement > 0:
        pass

    if avg_improvement > 3:
        pass
    else:
        pass


def main():
    """Run comparison."""
    py314 = load_results("314")
    py315 = load_results("315")

    if not py314 or not py315:
        sys.exit(1)

    compare_results(py314, py315)


if __name__ == "__main__":
    main()
