# Latency Metrics Dashboard - Learn Module

Hệ thống dashboard để theo dõi latency metrics cho phần **Learn** với Server Response và LLM Response (P90, P99 percentiles).

## 🚀 Quick Start

### Chạy với Docker (Khuyến nghị)

```bash
# Build và chạy
docker-compose up -d --build

# Xem logs
docker-compose logs -f

# Dừng
docker-compose down
```

**Truy cập Dashboard:** http://localhost:26003

### Initialize Data (Lần đầu)

```bash
# Fetch data cho 3 ngày trước với type='learn'
docker-compose exec backend python init_data.py 3
```

## 📁 Project Structure

```
.
├── backend/              # Backend API server
│   ├── app.py           # Flask API server
│   ├── evaluate.py      # Core logic for data processing
│   ├── init_data.py     # Script to initialize data
│   ├── requirements.txt # Python dependencies
│   └── Dockerfile       # Backend Docker image
├── frontend/            # Frontend dashboard
│   ├── dashboard.html   # Dashboard UI
│   ├── nginx.conf       # Nginx configuration
│   └── Dockerfile       # Frontend Docker image
├── docker-compose.yml   # Docker compose configuration
└── README.md           # This file
```

## 🔄 Logic Hoạt Động

### Daily Job (2:00 AM mỗi ngày)
1. Lấy conversation IDs từ API cho ngày hôm trước
2. Lấy response times (server_response_time, llm_response_time) cho từng conversation
3. Lưu vào bảng `latency_metric` với `type='learn'`

### UI Refresh
1. Lấy dữ liệu từ `latency_metric` với `type='learn'` (7 ngày gần nhất)
2. Tính toán p90, p99 cho server_response_time và llm_response_time
3. Hiển thị trên chart và bảng
4. Mỗi ngày chỉ hiển thị 1 điểm trên chart (aggregate tất cả bots)

## 🐳 Docker Deployment

### Build và chạy
```bash
docker-compose build
docker-compose up -d
```

### View logs
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Stop
```bash
docker-compose down
```

## 📝 Usage

### Initialize Data (First Time)
```bash
docker-compose exec backend python init_data.py 3
```

### Run Daily Job Manually
```bash
docker-compose exec backend python evaluate.py daily
```

### Run Scheduler (Auto 2:00 AM daily)
```bash
docker-compose exec backend python evaluate.py scheduler
```

## 🔌 API Endpoints

- `GET /api/metrics/last-7-days?type=learn` - Lấy metrics 7 ngày gần nhất (type=learn)
- `POST /api/metrics/refresh` - Refresh và tính lại metrics
- `GET /api/metrics/daily?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&type=learn` - Lấy metrics theo date range
- `POST /api/metrics/fetch-date` - Fetch và lưu data cho một ngày cụ thể (cần AUTH_TOKEN và MONITOR_TOKEN)
  ```json
  {
    "date": "2025-11-08",
    "type": "learn"
  }
  ```
- `GET /health` - Health check

## 🎨 UI Features

- **Line Chart**: Hiển thị P90, P99 của Server Response và LLM Response (7 ngày)
- **Stats Cards**: Trung bình 7 ngày cho các metrics
- **Daily Table**: Bảng chi tiết metrics theo từng ngày
- **Empty State**: Hiển thị khi chưa có dữ liệu
- **Auto Refresh**: Tự động refresh mỗi 5 phút

## ⚙️ Configuration

### Environment Variables

Tạo file `.env` trong thư mục gốc của project (copy từ `.env.example`):

```bash
cp .env.example .env
```

Sau đó chỉnh sửa file `.env` và thêm các tokens của bạn:

```env
# Database Configuration
DB_HOST=103.253.20.30
DB_PORT=26001
DB_NAME=robot-workflow-user-log-test
DB_USER=postgres
DB_PASSWORD=postgres

# API Tokens for fetching data (REQUIRED for Fetch Data feature)
AUTH_TOKEN=your_actual_auth_token_here
MONITOR_TOKEN=your_actual_monitor_token_here
```

**Lưu ý:** 
- `AUTH_TOKEN` và `MONITOR_TOKEN` là bắt buộc nếu bạn muốn sử dụng tính năng "Fetch Data" từ UI
- Sau khi cập nhật `.env`, cần restart containers:
  ```bash
  docker-compose down
  docker-compose up -d
  ```

### Database
Database configuration có thể được override bằng environment variables trong file `.env`:
```env
DB_HOST=103.253.20.30
DB_PORT=26001
DB_NAME=robot-workflow-user-log-test
DB_USER=postgres
DB_PASSWORD=postgres
```

### Metric Type
- Mặc định: `type='learn'`
- Daily job tự động lưu với `type='learn'`
- UI tự động filter theo `type='learn'`

## 🛠️ Development

### Local Development

1. Start backend:
```bash
cd backend
python app.py
```

2. Open frontend:
```bash
open frontend/dashboard.html
```

## 🐛 Troubleshooting

### Port conflict
- Backend: Port 5002
- Frontend: Port 26003
- Đổi port trong `docker-compose.yml` nếu cần

### Database connection error
- Kiểm tra DB credentials
- Đảm bảo database accessible

### No data in dashboard
- Chạy `init_data.py` để fetch data
- Hoặc sử dụng nút "Fetch Data" trên UI (cần set AUTH_TOKEN và MONITOR_TOKEN trong .env)
- Kiểm tra logs: `docker-compose logs backend`

### Fetch Data bị lỗi "AUTH_TOKEN and MONITOR_TOKEN must be set"
- Tạo file `.env` từ `.env.example`
- Thêm `AUTH_TOKEN` và `MONITOR_TOKEN` vào file `.env`
- Restart containers: `docker-compose down && docker-compose up -d`

### Empty state hiển thị
- Đây là bình thường nếu chưa có data
- Chạy daily job để lấy dữ liệu

## 📄 License

MIT
