#!/bin/bash
# Test runner for Chicago Events Chatbot
# Runs unit tests with coverage reporting

set -e

echo "🧪 Chicago Events Chatbot - Test Suite"
echo "======================================"
echo ""

# Install test dependencies
echo "📦 Installing test dependencies..."
uv pip install -e ".[test]" > /dev/null 2>&1

echo "✓ Dependencies installed"
echo ""

# Run tests with coverage
echo "🏃 Running tests with coverage..."
pytest tests/ \
    --cov=src \
    --cov-report=term-missing \
    --cov-report=html \
    -v \
    --tb=short

echo ""
echo "✓ Tests complete!"
echo ""
echo "📊 Coverage report generated in htmlcov/index.html"
echo ""
echo "Test Categories:"
echo "  Unit: pytest -m unit tests/"
echo "  Security: pytest -m security tests/"
echo "  Async: pytest -m asyncio tests/"
echo ""
echo "Quick commands:"
echo "  pytest tests/test_security.py -v     # Security tests"
echo "  pytest tests/test_resilience.py -v   # Resilience tests"
echo "  pytest tests/test_chatbot.py -v      # Chatbot tests"
