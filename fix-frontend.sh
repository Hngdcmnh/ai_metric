#!/bin/bash
# Script to fix frontend nginx config after container restart

echo "Waiting for frontend container to be ready..."
sleep 5

echo "Copying nginx config..."
docker cp frontend/nginx.conf latency-metrics-frontend:/etc/nginx/conf.d/default.conf

echo "Copying dashboard HTML..."
docker cp frontend/dashboard.html latency-metrics-frontend:/usr/share/nginx/html/index.html

echo "Testing nginx config..."
docker exec latency-metrics-frontend nginx -t

echo "Reloading nginx..."
docker exec latency-metrics-frontend nginx -s reload

echo "Done! Frontend should be working now."

