#!/bin/bash
# Start script - Build và fix tự động
# Usage: ./start.sh

echo "🚀 Starting AI Metric Dashboard..."
echo ""

# Build và start
echo "1. Building and starting containers..."
docker compose up -d --build

# Đợi containers start
echo "2. Waiting for containers..."
sleep 10

# Fix frontend
echo "3. Fixing frontend config..."
docker cp frontend/nginx.conf latency-metrics-frontend:/etc/nginx/conf.d/default.conf 2>/dev/null
docker exec latency-metrics-frontend nginx -t >/dev/null 2>&1 && \
    docker exec latency-metrics-frontend nginx -s reload 2>/dev/null && \
    echo "   ✓ Frontend config updated"

# Fix backend
echo "4. Fixing backend code..."
docker cp backend/app.py latency-metrics-backend:/app/app.py 2>/dev/null
docker cp backend/intent_accuracy.py latency-metrics-backend:/app/intent_accuracy.py 2>/dev/null
docker compose restart backend >/dev/null 2>&1
echo "   ✓ Backend code updated"

# Đợi services ready
echo "5. Waiting for services to be ready..."
sleep 15

# Test
echo ""
echo "6. Testing services..."
curl -f http://localhost:5002/health >/dev/null 2>&1 && echo "   ✓ Backend OK" || echo "   ✗ Backend FAILED"
curl -f http://localhost:26003/ >/dev/null 2>&1 && echo "   ✓ Frontend OK" || echo "   ✗ Frontend FAILED"

echo ""
echo "✅ Done!"
echo ""
echo "Services running:"
echo "  📊 Frontend: http://103.253.20.30:26003"
echo "  🔧 Backend:  http://103.253.20.30:5002"
echo ""
docker compose ps
