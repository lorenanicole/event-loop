# Development Setup Guide

Complete development environment setup for the Chicago Events Chatbot.

## Quick Start (5 minutes)

```bash
# 1. Install dependencies (dev + test)
uv pip install -e ".[dev,test]"

# 2. Install git hooks
invoke setup-hooks

# 3. You're ready!
invoke info  # See all available commands
```

## What's Installed

### Core Tools
- **invoke** - Task automation (like Make but Python)
- **ruff** - Fast linter + formatter (replaces black, isort, flake8)
- **pre-commit** - Git hooks framework

### Testing
- **pytest** - Unit testing
- **pytest-asyncio** - Async test support
- **pytest-cov** - Coverage reporting

### Security
- **ruff S rules** - Security scanning via flake8-bandit rules (built into ruff, no separate install)

## Common Development Tasks

### Running Tests

```bash
# All tests with coverage
invoke test

# Quick test (no coverage)
invoke test-quick

# Specific test file
invoke test --file security

# By category
invoke test-category --category security
invoke test-category --category database
invoke test-category --category api
```

### Code Quality

```bash
# Check code style (ruff)
invoke lint

# Auto-fix issues
invoke lint --fix

# Format code
invoke format

# Full security audit
invoke security-audit
```

### Pre-Commit Workflow

```bash
# Run full pre-commit checks (before git commit)
invoke pre-commit

# Or let git hooks do it automatically
git commit  # Hooks run automatically

# Re-run specific hook
pre-commit run ruff --all-files
```

### Maintenance

```bash
# Generate coverage report
invoke coverage

# Clean build artifacts
invoke clean

# Show all available commands
invoke info
```

## Git Hooks Workflow

After `invoke setup-hooks`, git hooks automatically run on commit:

1. **Ruff linting** - Checks code style
   - Auto-fixes simple issues (with `--fix`)
   - Fails on serious problems
   
2. **Ruff formatting** - Ensures consistent formatting

3. **Security check** - Scans for vulnerabilities (ruff S rules)

4. **Core tests** - Runs security + core tests
   - Stops commit if tests fail
   - Provides fast feedback

### Example Commit Flow

```bash
$ git commit -m "Add new feature"

# Git hooks run automatically:
✓ Ruff lint (auto-fix)     [0.2s]
✓ Ruff format               [0.1s]
✓ Security check (ruff S)   [0.1s]
✓ Security tests            [2.1s]
✓ Core functionality tests  [1.8s]

# Commit succeeds!
```

## Ruff Configuration

Ruff settings live in `backend/pyproject.toml` under `[tool.ruff.lint]`:

- **Target**: Python 3.15
- **Line length**: 100 chars
- **Rules selected**: B, BLE, DTZ, E, EXE, F, G, LOG, PLW, RUF, S, SIM, W
- **Globally ignored**: B008 (FastAPI Depends), BLE001 (deliberate broad except), EXE001 (scripts not chmod'd), G004 (f-string logging convention)
- **Per-file overrides**: scrapers ignore DTZ (intentionally naive datetimes); tests ignore S and DTZ; scripts ignore S, T20, E501

### Ruff commands

```bash
cd backend

# Check
python3 -m ruff check src/ tests/ scripts/ eval/

# Auto-fix safe issues
python3 -m ruff check src/ tests/ scripts/ eval/ --fix

# Format
python3 -m ruff format src/ tests/ scripts/ eval/

# Suppress one line
some_code  # noqa: E501
```

## Pre-Commit Configuration

Hooks defined in `.pre-commit-config.yaml`:

| Hook | Purpose | Auto-fix |
|------|---------|----------|
| ruff | Linting | ✅ Yes |
| ruff-format | Formatting | ✅ Yes |
| trailing-whitespace | Remove trailing spaces | ✅ Yes |
| end-of-file-fixer | Fix EOF | ✅ Yes |
| check-yaml | YAML syntax | ❌ No |
| check-toml | TOML syntax | ❌ No |
| debug-statements | Find debugger calls | ❌ No |
| ruff (S rules) | Security scan | ✅ Yes (noqa comments) |
| pytest-security | Security tests | ❌ No |
| pytest-core | Core tests | ❌ No |

### Skipping Hooks (When Necessary)

```bash
# Skip all hooks
git commit --no-verify

# Skip specific hook
SKIP=pytest-core git commit

# Skip pre-commit on rebase
git rebase -i --no-verify
```

## Invoke Task Reference

### Test Tasks
- `invoke test` - Run all tests with coverage
- `invoke test --file security` - Run specific test file
- `invoke test-quick` - Fast test run (no coverage)
- `invoke test-quick --fast` - Stop on first failure
- `invoke test-category --category security` - Run by category
- `invoke security-audit` - Security + resilience tests

### Code Quality
- `invoke lint` - Check code style
- `invoke lint --fix` - Auto-fix issues
- `invoke format` - Format all code
- `invoke pre-commit` - Run pre-commit checks

### Maintenance
- `invoke setup-hooks` - Install git hooks
- `invoke coverage` - Generate coverage report
- `invoke clean` - Clean build artifacts
- `invoke info` - Show all commands

## Common Workflows

### Before Creating a PR

```bash
# 1. Format code
invoke format

# 2. Run full checks
invoke pre-commit

# 3. Review coverage
invoke coverage

# 4. Commit
git add .
git commit -m "Feature description"
```

### After Pulling Changes

```bash
# Update hooks
pre-commit autoupdate

# Install any new hooks
invoke setup-hooks
```

### Troubleshooting Failed Hooks

**Linting error:**
```bash
invoke lint --fix
git add .
git commit
```

**Test failure:**
```bash
invoke test --file <name>  # Run specific test
# Fix the issue
git add .
git commit
```

**Hook not running:**
```bash
# Check hook installation
pre-commit run --all-files

# Reinstall
invoke setup-hooks
```

## Configuration Files

### `.ruff.toml`
Main linting and formatting config:
- Python 3.15 target
- 100 char line length
- Import sorting
- Rule selections

### `.pre-commit-config.yaml`
Git hook definitions:
- Which hooks to run
- Hook versions
- Per-hook configuration

### `pyproject.toml` — ruff security rules
Security scanning uses ruff's `S` (flake8-bandit) rules configured in
`[tool.ruff.lint]`. Per-file ignores suppress intentional patterns (e.g.
`S104` for the dev server bind-all, `S311` for persona rotation).

### `tasks.py`
Invoke task definitions:
- Test runners
- Linting tasks
- Setup tasks
- Utilities

## Python 3.15 Features Used

This project uses Python 3.15 features:
- PEP 649: Deferred evaluation of annotations
- Latest async/await patterns
- Type hints with `|` union syntax
- `match` statements (if used)

Ruff is configured for Python 3.15 to catch compatibility issues early.

## Tips & Tricks

### Run tests on file save (in your editor)
```bash
# In your editor's run command:
invoke test-quick --fast
```

### Faster CI checks
```bash
# Pre-commit already optimized, but you can:
SKIP=ruff invoke pre-commit  # Skip linting if you need to commit WIP
```

### Debug a failing test
```bash
invoke test --file security
# Add breakpoint in code
import pdb; pdb.set_trace()
# Run again
```

### View test coverage gaps
```bash
invoke coverage
# Open htmlcov/index.html in browser
```

## Next Steps

1. ✅ Install dependencies: `uv pip install -e ".[dev,test]"`
2. ✅ Setup hooks: `invoke setup-hooks`
3. ✅ View commands: `invoke info`
4. 🚀 Start developing!

For more details, see:
- [README.md](README.md) - Project overview
