#!/bin/bash
# Run EventLoop with dual Python versions:
# - Backend: Python 3.15 RC3 (new features, lazy imports, JIT)
# - Parser: Python 3.14 (stable, proven)

set -e

echo "=========================================="
echo "EventLoop Dual-Version Stack"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting Python 3.15 RC3 Backend Server...${NC}"
echo "  Features: lazy imports, frozendict, sentinel, upgraded JIT"
echo ""

# Start backend in background
cd /Users/lorenamesa/Workspace/python315
uv run --python 3.15.0rc3 python src/backend_server_315.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "✗ Backend failed to start"
    exit 1
fi

echo -e "${GREEN}✓ Backend running (PID: $BACKEND_PID)${NC}"
echo ""

# Now run parser client on Python 3.14
echo -e "${BLUE}Running Python 3.14 Parser Client...${NC}"
echo "  Stable version calling 3.15 backend via HTTP API"
echo ""

uv run --python 3.14 python src/parser_client_314.py
PARSER_EXIT=$?

# Cleanup: stop backend
echo ""
echo "Stopping backend..."
kill $BACKEND_PID 2>/dev/null || true
wait $BACKEND_PID 2>/dev/null || true

echo -e "${GREEN}✓ Dual-version stack completed${NC}"

exit $PARSER_EXIT
