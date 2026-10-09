# EventLoop Performance Benchmarks

Performance comparison between Python 3.14 and Python 3.15 (final, released October 9 2026).

## Running Benchmarks

### Python 3.14
```bash
uv run --python 3.14 python benchmarks/perf_compare.py
```

### Python 3.15
```bash
uv run --python 3.15 python benchmarks/perf_compare.py
```

## Metrics Tested

### 1. **Startup Time** (`startup_imports`)
- Tests lazy import benefit
- Measures time to import FastAPI, asyncio, json
- 3.15 benefits: lazy imports defer heavy modules

### 2. **Dict Operations** (`dict_operations`)
- 10,000 iterations of dict.get() and hash()
- 3.15 benefit: frozendict for immutable configs
- Measures: ops/sec, throughput

### 3. **List Comprehensions** (`list_comprehension`)
- 10,000 iterations of list flattening
- 3.15 benefit: unpacking syntax `[*chunk for chunk in data]`
- Measures: comprehension speed, syntax sugar benefit

### 4. **Async Operations** (`async_operations`)
- 1,000 async task creation and execution cycles
- 3.15 benefit: TaskGroup.cancel(), improved async handling
- Measures: task latency, context switch overhead

### 5. **JSON Operations** (`json_operations`)
- 5,000 encode/decode cycles
- 3.15 benefit: lazy import of json module
- Measures: serialization speed, common operation throughput

## Results Storage

Results are saved to `benchmarks/results/` as JSON:
- `benchmark_py314.json` - Python 3.14 results
- `benchmark_py315.json` - Python 3.15 results

## Expected Performance Improvements

| Feature | 3.14 vs 3.15 | Benefit |
|---------|-------------|---------|
| Startup Time | -5-10% | Lazy imports defer module loading |
| Async Operations | -7-12% | Upgraded JIT, improved bytecode |
| JSON Ops | -3-7% | JIT compilation of hot paths |
| Dict Operations | -2-5% | Better optimization |

## Comparing Results

Compare two benchmark runs:
```bash
python benchmarks/compare_results.py py314 py315
```

## Integration with CI/CD

Benchmarks can be run on every commit:
```bash
# Run benchmarks on both versions
uv run --python 3.14 python benchmarks/perf_compare.py
uv run --python 3.15 python benchmarks/perf_compare.py

# Store results for historical tracking
```

## Notes

- **Lazy Imports**: Python 3.15 benefit is most visible in CLI tools that import heavy deps
- **JIT Compiler**: Experimental in 3.15, must be enabled with `PYTHON_JIT=1`
- **frozendict**: 3.15 immutable dict for configs, hashing, and caching
- **Sentinel**: Proper replacement for module-level `object()` sentinels

## Blog Post Material

These benchmarks will support the blog post:
- "Python 3.15 in Production: Real Performance Gains"
- "Scaling EventLoop with Lazy Imports and JIT"
- "Why We Chose Python 3.15 for Our Chat Backend"
