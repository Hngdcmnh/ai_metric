# Deployment Guide

## 🚀 Deploy lên Server

### Yêu cầu
- Docker và Docker Compose đã được cài đặt
- Port 26003 và 5002 phải mở trên firewall

### Các bước deploy

1. **Clone project và vào thư mục:**
```bash
cd "AI Metric"
```

2. **Kiểm tra cấu hình database trong `docker-compose.yml`:**
   - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
   - Mặc định đã được cấu hình sẵn

3. **Build và chạy containers:**
```bash
docker-compose up -d --build
```

4. **Kiểm tra containers đang chạy:**
```bash
docker-compose ps
```

5. **Xem logs nếu có lỗi:**
```bash
# Xem logs backend
docker-compose logs -f backend

# Xem logs frontend
docker-compose logs -f frontend

# Xem tất cả logs
docker-compose logs -f
```

6. **Truy cập Dashboard:**
   - URL: `http://<server-ip>:26003`
   - Backend API: `http://<server-ip>:5002`

### Initialize Data (Lần đầu)

```bash
# Fetch data cho 3 ngày trước
docker-compose exec backend python init_data.py 3
```

### Các lệnh hữu ích

```bash
# Dừng services
docker-compose down

# Restart services
docker-compose restart

# Rebuild và restart
docker-compose up -d --build

# Xem status
docker-compose ps

# Xem logs real-time
docker-compose logs -f

# Vào container backend
docker-compose exec backend bash

# Health check backend
curl http://localhost:5002/health
```

### Ports
- **Frontend UI**: 26003
- **Backend API**: 5002

### Troubleshooting

1. **Port đã được sử dụng:**
   - Kiểm tra: `lsof -i :26003` hoặc `lsof -i :5002`
   - Dừng process đang sử dụng port hoặc đổi port trong `docker-compose.yml`

2. **Backend không kết nối được database:**
   - Kiểm tra DB_HOST, DB_PORT trong `docker-compose.yml`
   - Kiểm tra firewall có cho phép kết nối đến database không

3. **Frontend không load được:**
   - Kiểm tra backend có đang chạy không: `curl http://localhost:5002/health`
   - Kiểm tra logs frontend: `docker-compose logs frontend`

4. **Containers không start:**
   - Xem logs: `docker-compose logs`
   - Rebuild: `docker-compose up -d --build --force-recreate`

