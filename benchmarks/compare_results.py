#!/usr/bin/env python3
"""
Compare benchmark results between Python 3.14 and 3.15 RC3
"""

import json
import sys
from pathlib import Path
from typing import Dict, List


def load_results(version: str) -> Dict:
    """Load benchmark results for a version."""
    results_dir = Path(__file__).parent / "results"
    file = results_dir / f"benchmark_py{version}.json"

    if not file.exists():
        print(f"Error: {file} not found")
        return None

    with open(file) as f:
        return json.load(f)


def compare_results(py314: Dict, py315: Dict) -> None:
    """Compare results and show improvements."""
    print("\n" + "="*80)
    print("PERFORMANCE COMPARISON: Python 3.14 vs 3.15 RC3")
    print("="*80 + "\n")

    benchmarks_314 = {b["name"]: b for b in py314["benchmarks"]}
    benchmarks_315 = {b["name"]: b for b in py315["benchmarks"]}

    print(f"{'Benchmark':<30} {'3.14':<15} {'3.15':<15} {'Change':<15} {'Verdict':<15}")
    print("-" * 90)

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
            verdict = f"✓ Faster {change_pct:.1f}%"
            improvements.append((name, change_pct))
        elif change_pct < 0:
            verdict = f"✗ Slower {abs(change_pct):.1f}%"
        else:
            verdict = "≈ Same"

        print(
            f"{name:<30} {time_314:>12.2f}ms {time_315:>12.2f}ms "
            f"{change_pct:>12.1f}% {verdict:<15}"
        )

    print("\n" + "="*80)
    avg_improvement = total_improvement / len(benchmarks_314)
    print(f"\nAverage Improvement: {avg_improvement:.1f}%")
    print(f"Tests: {len(benchmarks_314)}")

    if improvements:
        print("\n✓ Performance Wins (3.15 faster than 3.14):")
        for name, pct in sorted(improvements, key=lambda x: x[1], reverse=True):
            print(f"  • {name}: +{pct:.1f}% faster")

    print("\n" + "="*80)

    # Insights
    print("\nKEY INSIGHTS:")
    print("-" * 80)

    json_improvement = next((p for n, p in improvements if n == "json_operations"), 0)
    async_improvement = next((p for n, p in improvements if n == "async_operations"), 0)

    if json_improvement > 5:
        print(f"✓ JSON ops improved {json_improvement:.1f}% - JIT compiler benefit")
    if async_improvement > 0:
        print(f"✓ Async ops improved - better event loop handling in 3.15")

    print("\nRECOMMENDATION:")
    if avg_improvement > 3:
        print("✓ Python 3.15 RC3 shows measurable performance improvements")
        print("  Recommended for production backends with CPU-intensive workloads")
    else:
        print("≈ Performance gains are modest but consistent")
        print("  Upgrade for new 3.15 features; performance gains are secondary")

    print("="*80 + "\n")


def main():
    """Run comparison."""
    py314 = load_results("314")
    py315 = load_results("315")

    if not py314 or not py315:
        sys.exit(1)

    compare_results(py314, py315)


if __name__ == "__main__":
    main()
