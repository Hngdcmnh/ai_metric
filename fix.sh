#!/bin/bash
# Quick fix script - run this after docker compose up -d

echo "Fixing frontend nginx config..."
sleep 5
docker cp frontend/nginx.conf latency-metrics-frontend:/etc/nginx/conf.d/default.conf
docker exec latency-metrics-frontend nginx -t && docker exec latency-metrics-frontend nginx -s reload
echo "✓ Frontend fixed"

echo "Fixing backend code..."
docker cp backend/app.py latency-metrics-backend:/app/app.py
docker cp backend/intent_accuracy.py latency-metrics-backend:/app/intent_accuracy.py
docker compose restart backend
echo "✓ Backend fixed"

echo "Waiting for services..."
sleep 15

echo "Testing..."
curl -f http://localhost:5002/health >/dev/null 2>&1 && echo "✓ Backend OK" || echo "✗ Backend FAILED"
curl -f http://localhost:26003/ >/dev/null 2>&1 && echo "✓ Frontend OK" || echo "✗ Frontend FAILED"

echo ""
echo "Done! Services should be running:"
echo "  Backend: http://103.253.20.30:5002"
echo "  Frontend: http://103.253.20.30:26003"

