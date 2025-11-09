# 🚀 Quick Start Guide

## Chạy với Docker (Khuyến nghị)

### 1. Build và chạy

```bash
# Build images
docker-compose build

# Start containers
docker-compose up -d

# Xem logs
docker-compose logs -f
```

### 2. Initialize Data (Lần đầu)

```bash
# Fetch data cho 3 ngày trước
docker-compose exec backend python init_data.py 3
```

### 3. Truy cập Dashboard

- **Frontend**: http://localhost
- **Backend API**: http://localhost:5001
- **Health check**: http://localhost:5001/health

## Chạy Local Development

### Backend
```bash
cd backend
pip install -r requirements.txt
python app.py
```

### Frontend
Mở `frontend/dashboard.html` trong trình duyệt

## Các lệnh hữu ích

### Docker
```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Restart
docker-compose restart

# Clean up
docker-compose down -v
```

### Initialize Data
```bash
docker-compose exec backend python init_data.py 3
```

### Run Daily Job
```bash
docker-compose exec backend python evaluate.py daily
```

### Run Scheduler
```bash
docker-compose exec backend python evaluate.py scheduler
```

## Troubleshooting

### Port đã được sử dụng
- Đổi port trong `docker-compose.yml`
- Hoặc dừng process đang dùng port

### Không kết nối được database
- Kiểm tra DB credentials
- Đảm bảo database accessible từ Docker network

### Dashboard không hiển thị dữ liệu
- Chạy `init_data.py` để fetch data
- Kiểm tra backend logs: `docker-compose logs backend`

## Cấu trúc Project

```
.
├── backend/          # Backend API server
├── frontend/         # Frontend dashboard
├── docker-compose.yml
└── README.md
```

## Cần giúp đỡ?

Xem file `README.md` hoặc `DOCKER.md` để biết thêm chi tiết.
