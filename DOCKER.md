# Docker Deployment Guide

## Quick Start

### 1. Build và chạy containers

```bash
# Build images
docker-compose build

# Start containers
docker-compose up -d

# Xem logs
docker-compose logs -f
```

### 2. Truy cập Dashboard

- Frontend: http://localhost
- Backend API: http://localhost:5001
- Health check: http://localhost:5001/health

### 3. Initialize Data (Lần đầu)

```bash
# Fetch data cho 3 ngày trước
docker-compose exec backend python init_data.py 3
```

## Cấu trúc Docker

### Backend Container
- Image: Python 3.11-slim
- Port: 5001
- Health check: `/health` endpoint

### Frontend Container
- Image: Nginx Alpine
- Port: 80
- Serve static files và proxy API requests

## Environment Variables

Tạo file `.env` để cấu hình:

```bash
DB_HOST=103.253.20.30
DB_PORT=26001
DB_NAME=robot-workflow-user-log-test
DB_USER=postgres
DB_PASSWORD=postgres
PORT=5001
HOST=0.0.0.0
```

## Commands

### Build
```bash
docker-compose build
```

### Start
```bash
docker-compose up -d
```

### Stop
```bash
docker-compose down
```

### View logs
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Restart
```bash
docker-compose restart
```

### Clean up
```bash
docker-compose down -v
```

## Troubleshooting

### Container không start
```bash
# Check logs
docker-compose logs backend
docker-compose logs frontend

# Check container status
docker-compose ps
```

### Database connection error
- Kiểm tra DB credentials trong `.env`
- Đảm bảo database accessible từ Docker network
- Test connection: `docker-compose exec backend python evaluate.py test`

### Port conflict
- Đổi port trong `docker-compose.yml`
- Hoặc stop process đang dùng port

## Production Deployment

### 1. Update environment variables
Tạo file `.env.production` với production values

### 2. Build production images
```bash
docker-compose -f docker-compose.yml build
```

### 3. Deploy
```bash
docker-compose -f docker-compose.yml up -d
```

### 4. Setup reverse proxy (optional)
Cấu hình nginx hoặc traefik để:
- SSL/TLS
- Domain name
- Load balancing

## Monitoring

### Health checks
```bash
curl http://localhost:5001/health
```

### View metrics
```bash
curl http://localhost:5001/api/metrics/last-7-days
```

