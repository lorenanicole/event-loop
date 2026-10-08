"""
Invoke tasks for development automation.
Run with: invoke <task-name>

Examples:
  invoke test                  # Run all tests
  invoke test --file security  # Run specific test file
  invoke lint                  # Check code style
  invoke format               # Auto-format code
  invoke pre-commit           # Pre-commit checks (tests + lint)
"""

import sys

from invoke import Collection, task

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(msg):
    """Print a formatted header."""


def print_success(msg):
    """Print success message."""


def print_error(msg):
    """Print error message."""


def print_warning(msg):
    """Print warning message."""


@task(help={"file": "Specific test file to run (e.g., 'security')"})
def test(c, file=None):
    """Run unit tests with pytest."""
    print_header("Running Tests")

    cmd = "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/"

    if file:
        cmd += f"/test_{file}.py"

    cmd += " -v --cov=src --cov-report=term-missing"

    result = c.run(cmd, warn=True)

    if result.ok:
        print_success("All tests passed!")
    else:
        print_error("Some tests failed!")
        sys.exit(1)


@task(help={"fast": "Quick check without full coverage"})
def test_quick(c, fast=False):
    """Run tests quickly (no coverage report)."""
    print_header("Quick Test Run")

    cmd = "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/ -v --tb=short"

    if fast:
        cmd += " -x"  # Stop on first failure

    result = c.run(cmd, warn=True)

    if not result.ok:
        sys.exit(1)


@task(help={"fix": "Auto-fix issues"})
def lint(c, fix=False):
    """Check code with ruff."""
    print_header("Code Quality Check (Ruff)")

    cmd = "ruff check backend/src backend/tests"

    if fix:
        cmd += " --fix"

    result = c.run(cmd, warn=True)

    if result.ok:
        print_success("Code passes all checks!")
    else:
        if fix:
            print_warning("Attempted to fix issues, review changes")
        else:
            print_error("Code has linting issues")
            print_warning("Run 'invoke lint --fix' to auto-fix")
            sys.exit(1)


@task
def format(c):
    """Format code with ruff."""
    print_header("Code Formatting (Ruff)")

    # Ruff format
    c.run("ruff format backend/src backend/tests", warn=True)

    # Then check
    c.run("ruff check backend/src backend/tests --fix", warn=True)

    print_success("Code formatted!")


@task
def pre_commit(c):
    """Run pre-commit checks: lint + test."""
    print_header("Pre-Commit Checks")

    # First lint
    lint_result = c.run("ruff check backend/src backend/tests", warn=True)

    if not lint_result.ok:
        print_error("Linting failed! Run 'invoke lint --fix'")
        sys.exit(1)

    print_success("Linting passed!")

    # Then test
    test_result = c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/ -v --tb=short --co -q",  # Just collect, don't run
        warn=True,
    )

    # Run actual tests
    test_result = c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/ -x --tb=short",  # Stop on first failure
        warn=True,
    )

    if not test_result.ok:
        print_error("Tests failed!")
        sys.exit(1)

    print_success("Tests passed!")

    print_header("✓ Ready to commit!")


@task
def setup_hooks(c):
    """Install git pre-commit hooks."""
    print_header("Setting Up Git Hooks")

    # Install pre-commit
    c.run("pip install pre-commit", warn=True)

    # Install hooks
    c.run("pre-commit install", warn=True)

    print_success("Git hooks installed!")


@task
def clean(c):
    """Clean up generated files."""
    print_header("Cleaning Up")

    patterns = [
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".coverage",
        "htmlcov",
        ".ruff_cache",
        "dist",
        "build",
        "*.egg-info",
    ]

    for pattern in patterns:
        c.run(f"find . -type d -name '{pattern}' -exec rm -rf {{}} + 2>/dev/null || true")
        c.run(f"find . -type f -name '{pattern}' -delete 2>/dev/null || true")

    print_success("Cleaned up!")


@task
def coverage(c):
    """Generate detailed coverage report."""
    print_header("Coverage Report")

    c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/ --cov=src --cov-report=html --cov-report=term-missing -v"
    )

    print_success("Coverage report generated in htmlcov/index.html")


@task(help={"category": "Test category (security, database, api, scraper)"})
def test_category(c, category):
    """Run tests by category."""
    print_header(f"Running {category.title()} Tests")

    result = c.run(
        f"cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/ -k {category} -v --tb=short",
        warn=True,
    )

    if not result.ok:
        sys.exit(1)


@task
def security_audit(c):
    """Run security-focused tests."""
    print_header("Security Audit")

    c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/app/test_security.py -v",
        warn=True,
    )

    c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python -m pytest tests/app/test_resilience.py -v",
        warn=True,
    )

    print_success("Security audit complete!")


@task
def scrape(c):
    """Scrape events from all Chicago sources and populate database."""
    print_header("Scraping Events from All Sources")
    c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python scripts/additive_scrape.py",
        pty=True,
    )


@task
def dev(c):
    """Run backend server with uv."""
    print_header("Starting Backend (EventLoop API)")
    c.run(
        "cd backend && PYTHONPATH=src:. .venv/bin/python -m uvicorn app.main:app "
        "--reload --reload-dir src --port 8000",
        pty=True,
    )


@task
def frontend(c):
    """Run frontend dev server."""
    print_header("Starting Frontend (Vite)")
    c.run("cd frontend && npm run dev", pty=True)


@task
def info(c):
    """Show project info and commands."""
    print_header("Chicago Events Chatbot - Development")


# Create command collection
ns = Collection()
ns.add_task(scrape)
ns.add_task(dev)
ns.add_task(frontend)
ns.add_task(test)
ns.add_task(test_quick)
ns.add_task(lint)
ns.add_task(format)
ns.add_task(pre_commit)
ns.add_task(setup_hooks)
ns.add_task(clean)
ns.add_task(coverage)
ns.add_task(test_category)
ns.add_task(security_audit)
ns.add_task(info)

# Set defaults
ns.configure({"run": {"pty": True, "echo": True}})
