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

from invoke import task, Collection
import sys


# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(msg):
    """Print a formatted header."""
    print(f"\n{BOLD}{GREEN}{'='*60}{RESET}")
    print(f"{BOLD}{GREEN}{msg}{RESET}")
    print(f"{BOLD}{GREEN}{'='*60}{RESET}\n")


def print_success(msg):
    """Print success message."""
    print(f"{GREEN}✓ {msg}{RESET}")


def print_error(msg):
    """Print error message."""
    print(f"{RED}✗ {msg}{RESET}")


def print_warning(msg):
    """Print warning message."""
    print(f"{YELLOW}⚠ {msg}{RESET}")


@task(help={"file": "Specific test file to run (e.g., 'security')"})
def test(c, file=None):
    """Run unit tests with pytest."""
    print_header("Running Tests")

    cmd = "pytest tests/"

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

    cmd = "pytest tests/ -v --tb=short"

    if fast:
        cmd += " -x"  # Stop on first failure

    result = c.run(cmd, warn=True)

    if not result.ok:
        sys.exit(1)


@task(help={"fix": "Auto-fix issues"})
def lint(c, fix=False):
    """Check code with ruff."""
    print_header("Code Quality Check (Ruff)")

    cmd = "ruff check src/ tests/"

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
    c.run("ruff format src/ tests/", warn=True)

    # Then check
    c.run("ruff check src/ tests/ --fix", warn=True)

    print_success("Code formatted!")


@task
def pre_commit(c):
    """Run pre-commit checks: lint + test."""
    print_header("Pre-Commit Checks")

    # First lint
    print("\n1️⃣  Linting...")
    lint_result = c.run("ruff check src/ tests/", warn=True)

    if not lint_result.ok:
        print_error("Linting failed! Run 'invoke lint --fix'")
        sys.exit(1)

    print_success("Linting passed!")

    # Then test
    print("\n2️⃣  Testing...")
    test_result = c.run(
        "pytest tests/ -v --tb=short --co -q",  # Just collect, don't run
        warn=True
    )

    # Run actual tests
    test_result = c.run(
        "pytest tests/ -x --tb=short",  # Stop on first failure
        warn=True
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
    print("\nHooks will run on 'git commit':")
    print("  • Ruff linting")
    print("  • Unit tests (security + core tests)")
    print("  • File formatting")


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
        "pytest tests/ --cov=src --cov-report=html --cov-report=term-missing -v"
    )

    print_success("Coverage report generated in htmlcov/index.html")


@task(help={"category": "Test category (security, database, api, scraper)"})
def test_category(c, category):
    """Run tests by category."""
    print_header(f"Running {category.title()} Tests")

    result = c.run(
        f"pytest tests/ -k {category} -v --tb=short",
        warn=True
    )

    if not result.ok:
        sys.exit(1)


@task
def security_audit(c):
    """Run security-focused tests."""
    print_header("Security Audit")

    print("\n1️⃣  Security tests...")
    c.run("pytest tests/test_security.py -v", warn=True)

    print("\n2️⃣  Resilience tests...")
    c.run("pytest tests/test_resilience.py -v", warn=True)

    print_success("Security audit complete!")


@task
def info(c):
    """Show project info and commands."""
    print_header("Chicago Events Chatbot - Development")

    print(f"""
{BOLD}Quick Commands:{RESET}
  invoke test              # Run all tests
  invoke test --file security  # Run security tests
  invoke lint              # Check code style
  invoke format            # Format code
  invoke pre-commit        # Pre-commit checks
  invoke setup-hooks       # Install git hooks
  invoke clean             # Clean build artifacts
  invoke coverage          # Generate coverage report

{BOLD}Test Categories:{RESET}
  invoke test-category --category security   # Security tests
  invoke test-category --category database   # Database tests
  invoke test-category --category api        # API tests
  invoke test-category --category scraper    # Scraper tests

{BOLD}Code Quality:{RESET}
  invoke security-audit    # Security + resilience tests
  invoke lint --fix        # Auto-fix linting issues
  invoke format            # Format all code

{BOLD}Dependencies:{RESET}
  Install with: uv pip install -e ".[dev,test]"
    • pytest: Testing framework
    • ruff: Fast linter + formatter
    • invoke: Task automation
    • pre-commit: Git hooks

{BOLD}Git Workflow:{RESET}
  1. Make changes
  2. Run 'invoke pre-commit' (or let git hooks do it)
  3. Git commit
  4. Push!
""")


# Create command collection
ns = Collection()
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
