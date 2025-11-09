#!/bin/bash

# Script to start the API server
# Usage: ./start_server.sh

echo "🚀 Starting Latency Metrics API Server..."
echo ""

# Check if port 5001 is already in use
if lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null ; then
    echo "❌ Port 5001 is already in use!"
    echo "   Please stop the process using port 5001 or change the port in api_server.py"
    exit 1
fi

# Start the API server
python3 api_server.py


