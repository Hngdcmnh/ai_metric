#!/bin/bash
# Build script for AI Metric Dashboard
# Backend: port 5002, Frontend: port 26003

echo "Building backend and frontend images..."
echo "Note: If you get permission error, use: sudo docker compose build"
docker compose build || {
    echo "Build failed. Trying with sudo..."
    sudo docker compose build
}

echo "Starting containers..."
docker compose up -d

echo "Waiting for services to be ready..."
sleep 15

echo "Fixing frontend nginx config (if needed)..."
sleep 5
docker cp frontend/nginx.conf latency-metrics-frontend:/etc/nginx/conf.d/default.conf 2>/dev/null
docker exec latency-metrics-frontend nginx -t >/dev/null 2>&1 && \
    docker exec latency-metrics-frontend nginx -s reload 2>/dev/null && \
    echo "✓ Frontend config updated"

echo "Ensuring backend has latest code..."
docker cp backend/app.py latency-metrics-backend:/app/app.py 2>/dev/null
docker cp backend/intent_accuracy.py latency-metrics-backend:/app/intent_accuracy.py 2>/dev/null
docker compose restart backend >/dev/null 2>&1
sleep 10

echo "Checking backend health..."
curl -f http://localhost:5002/health >/dev/null 2>&1 && echo "✓ Backend OK" || echo "✗ Backend FAILED"

echo "Checking frontend..."
curl -f http://localhost:26003/ >/dev/null 2>&1 && echo "✓ Frontend OK" || echo "✗ Frontend FAILED"

echo ""
echo "Services should be running:"
echo "  Backend: http://localhost:5002"
echo "  Frontend: http://localhost:26003"
echo ""
docker compose ps

