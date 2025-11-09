#!/bin/bash

# Script to start the API server and open dashboard
# Usage: ./start.sh

PORT=5001
API_URL="http://localhost:${PORT}"

echo "🚀 Starting Latency Metrics Dashboard..."
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 is not installed!"
    exit 1
fi

# Check if port 5001 is already in use
EXISTING_PID=$(lsof -ti:${PORT} 2>/dev/null)
if [ ! -z "$EXISTING_PID" ]; then
    echo "⚠️  Port ${PORT} is already in use (PID: $EXISTING_PID)"
    echo "   Using existing server..."
    SERVER_PID=$EXISTING_PID
else
    echo "📡 Starting API server on port ${PORT}..."
    # Start API server in background
    python3 api_server.py > server.log 2>&1 &
    SERVER_PID=$!
    echo "✅ API server started (PID: $SERVER_PID)"
    echo "   Waiting for server to be ready..."
    
    # Wait for server to start and be ready
    MAX_WAIT=15
    for i in $(seq 1 $MAX_WAIT); do
        sleep 1
        if curl -s "${API_URL}/health" > /dev/null 2>&1; then
            echo "✅ Server is ready!"
            break
        fi
        if [ $i -eq $MAX_WAIT ]; then
            echo "❌ Server failed to start after ${MAX_WAIT} seconds"
            echo "   Check server.log for details:"
            tail -20 server.log
            kill $SERVER_PID 2>/dev/null
            exit 1
        fi
        echo -n "."
    done
    echo ""
fi

# Final check if server is responding
if curl -s "${API_URL}/health" > /dev/null 2>&1; then
    echo ""
    echo "✅ API server is running on ${API_URL}"
    echo ""
    
    # Get the absolute path to dashboard.html
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    DASHBOARD_PATH="${SCRIPT_DIR}/dashboard.html"
    
    echo "🌐 Opening dashboard in your browser..."
    echo ""
    
    # Open dashboard in default browser
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        open "${DASHBOARD_PATH}"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        xdg-open "file://${DASHBOARD_PATH}" 2>/dev/null || sensible-browser "file://${DASHBOARD_PATH}" 2>/dev/null
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        # Windows
        start "file://${DASHBOARD_PATH}"
    else
        echo "⚠️  Please open dashboard.html manually in your browser"
    fi
    
    echo "📊 Dashboard: file://${DASHBOARD_PATH}"
    echo "🔗 API Server: ${API_URL}"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Dashboard is ready!"
    echo "   Press Ctrl+C to stop the server"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # If we started the server, wait for it. Otherwise just exit
    if [ -z "$EXISTING_PID" ]; then
        # Trap Ctrl+C to cleanup
        trap "echo ''; echo '🛑 Stopping server...'; kill $SERVER_PID 2>/dev/null; exit 0" INT TERM
        # Wait for server process
        wait $SERVER_PID
    else
        echo "Server is running in background (PID: $SERVER_PID)"
        echo "To stop it, run: kill $SERVER_PID"
    fi
else
    echo "❌ API server is not responding"
    echo "   Check server.log for errors:"
    tail -20 server.log 2>/dev/null || echo "   No server.log found"
    if [ ! -z "$SERVER_PID" ] && [ -z "$EXISTING_PID" ]; then
        kill $SERVER_PID 2>/dev/null
    fi
    exit 1
fi

