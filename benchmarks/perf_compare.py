#!/usr/bin/env python3
"""
Performance Benchmark: Python 3.14 vs 3.15 RC3
Measures startup time, request latency, scraping speed, and JIT impact
"""

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""

    name: str
    python_version: str
    duration_ms: float
    iterations: int = 1
    ops_per_sec: float = None

    def __post_init__(self):
        if self.iterations > 1:
            self.ops_per_sec = (self.iterations * 1000) / self.duration_ms


class Benchmarks:
    """Suite of performance benchmarks."""

    def __init__(self):
        self.results: list[BenchmarkResult] = []
        self.python_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

    def benchmark_startup_time(self) -> BenchmarkResult:
        """Measure module import time (lazy imports benefit)."""
        start = time.perf_counter()

        # Simulate lazy imports

        duration_ms = (time.perf_counter() - start) * 1000
        result = BenchmarkResult(
            name="startup_imports", python_version=self.python_version, duration_ms=duration_ms
        )
        self.results.append(result)
        return result

    def benchmark_dict_operations(self) -> BenchmarkResult:
        """Measure dict operations (frozendict available in 3.15)."""
        iterations = 10_000

        # Use regular dict (works on both versions)
        test_dict = {"theme": "light", "autosave": True}

        start = time.perf_counter()
        for _ in range(iterations):
            _ = test_dict.get("theme")
            _ = test_dict.get("autosave")
            _ = id(test_dict)

        duration_ms = (time.perf_counter() - start) * 1000
        result = BenchmarkResult(
            name="dict_operations",
            python_version=self.python_version,
            duration_ms=duration_ms,
            iterations=iterations,
        )
        self.results.append(result)
        return result

    def benchmark_list_comprehension(self) -> BenchmarkResult:
        """Measure list comprehension performance."""
        iterations = 10_000
        data = [[1, 2, 3], [4, 5], [6, 7, 8, 9]]

        start = time.perf_counter()
        for _ in range(iterations):
            # Traditional comprehension (both 3.14 and 3.15)
            result = [item for chunk in data for item in chunk]

        duration_ms = (time.perf_counter() - start) * 1000
        result = BenchmarkResult(
            name="list_comprehension",
            python_version=self.python_version,
            duration_ms=duration_ms,
            iterations=iterations,
        )
        self.results.append(result)
        return result

    async def benchmark_async_operations(self) -> BenchmarkResult:
        """Measure async task creation and execution."""
        iterations = 1_000

        async def dummy_task():
            await asyncio.sleep(0.0001)
            return 42

        start = time.perf_counter()
        for _ in range(iterations):
            task = asyncio.create_task(dummy_task())
            await task

        duration_ms = (time.perf_counter() - start) * 1000
        result = BenchmarkResult(
            name="async_operations",
            python_version=self.python_version,
            duration_ms=duration_ms,
            iterations=iterations,
        )
        self.results.append(result)
        return result

    def benchmark_json_operations(self) -> BenchmarkResult:
        """Measure JSON encode/decode (lazy import scenario)."""
        iterations = 5_000
        data = {
            "events": [
                {"name": f"Event {i}", "date": "2026-10-05", "location": "Chicago"}
                for i in range(10)
            ]
        }

        start = time.perf_counter()
        for _ in range(iterations):
            json_str = json.dumps(data)
            _ = json.loads(json_str)

        duration_ms = (time.perf_counter() - start) * 1000
        result = BenchmarkResult(
            name="json_operations",
            python_version=self.python_version,
            duration_ms=duration_ms,
            iterations=iterations,
        )
        self.results.append(result)
        return result

    def run_all(self) -> list[BenchmarkResult]:
        """Run all benchmarks."""

        # Sync benchmarks
        self.benchmark_startup_time()
        self.benchmark_dict_operations()
        self.benchmark_list_comprehension()
        self.benchmark_json_operations()

        # Async benchmarks
        asyncio.run(self.benchmark_async_operations())

        return self.results

    def report(self) -> str:
        """Generate human-readable report."""
        lines = [
            "\n" + "=" * 70,
            "BENCHMARK RESULTS",
            "=" * 70 + "\n",
            f"{'Benchmark':<30} {'Duration (ms)':<15} {'Ops/Sec':<15}",
            "-" * 70,
        ]

        for result in self.results:
            ops_sec = f"{result.ops_per_sec:.0f}" if result.ops_per_sec else "N/A"
            lines.append(f"{result.name:<30} {result.duration_ms:>12.2f}ms {ops_sec:>14}")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)

    def to_json(self) -> str:
        """Export results as JSON."""
        data = {
            "python_version": self.python_version,
            "benchmarks": [
                {
                    "name": r.name,
                    "duration_ms": r.duration_ms,
                    "iterations": r.iterations,
                    "ops_per_sec": r.ops_per_sec,
                }
                for r in self.results
            ],
        }
        return json.dumps(data, indent=2)


def main():
    """Run benchmarks and save results."""
    benchmarks = Benchmarks()
    benchmarks.run_all()

    # Print report

    # Save JSON results
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    version_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    output_file = results_dir / f"benchmark_{version_tag}.json"
    output_file.write_text(benchmarks.to_json())



if __name__ == "__main__":
    main()
