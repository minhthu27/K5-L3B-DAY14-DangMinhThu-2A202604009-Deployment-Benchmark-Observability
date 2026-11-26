# Deployment — agent Part 6

## Thông tin deploy

| Mục | Giá trị |
|---|---|
| Nền tảng | Railway (project `vigilant-recreation`, environment `production`, region `sfo`) |
| URL public | **https://k5-agent-production.up.railway.app** |
| Ngày deploy | 2026-11-26 |
| Service agent | `k5-agent` (build từ `06-lab-complete/Dockerfile` theo `railway.toml`, builder `DOCKERFILE`, `healthcheckPath = "/health"`) |
| Redis | Railway Redis `Redis-8XTw` (mạng nội bộ); `REDIS_URL` là biến tham chiếu `${{Redis-8XTw.REDIS_URL}}` |
| Cổng | Railway cấp `PORT=8080`; Dockerfile lắng nghe `${PORT:-8000}` |

## Biến môi trường đã đặt trên Railway (chỉ ghi **tên**)

`AGENT_API_KEY` (secret), `REDIS_URL` (tham chiếu tới Redis của Railway), `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`. `PORT` do Railway cấp. Không biến nào nằm trong code hay trong git.

## Lệnh kiểm tra và kết quả

```bash
BASE="https://k5-agent-production.up.railway.app"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"       # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

| Lệnh | Mong đợi | Kết quả thật (2026-11-26) |
|---|---|---|
| `GET /health` | 200 | **200** `{"status":"ok"}` |
| `GET /ready` | 200 | **200** `{"status":"ready"}` (Redis đã nối) |
| `POST /ask` không key | 401 | **401** `{"detail":"Invalid or missing API key"}` |
| `POST /ask` có key | 200 | **200** (chủ bài chạy bằng key thật của mình) |

Ba lệnh đầu cũng đã được kiểm tra độc lập từ bên ngoài ngay sau khi nối Redis đúng.

## Ghi chú trong quá trình deploy

- Lần deploy đầu bị crash vì lệnh `railway add --database redis` đổi service đang được liên kết sang Redis, nên `railway up` đã đẩy code agent đè lên service Redis (log: `exec: docker-entrypoint.sh: not found`). Cách sửa: tạo service riêng `k5-agent`, dùng `--service k5-agent` ở mọi lệnh, và trỏ `REDIS_URL` tới Redis mới. Service Redis hỏng đã bị xoá.
- Cảnh báo "Config as Code (railway.toml) is deprecated" của Railway không ảnh hưởng: file vẫn hoạt động đến 2026-12-01. `render.yaml` được giữ làm cấu hình dự phòng cho Render.

## Ảnh (trong `screenshots/`)

- `dashboard.png` — dashboard Railway, service `k5-agent` ở trạng thái ACTIVE, "Deployment successful", domain `k5-agent-production.up.railway.app`
- `railway-variables.png` — tab Variables của `k5-agent`: 5 biến (`AGENT_API_KEY`, `DAILY_BUDGET_USD`, `ENVIRONMENT`, `RATE_LIMIT_PER_MINUTE`, `REDIS_URL`), giá trị được ẩn
- `running.png` — log `startup` / `Uvicorn running`
- `test.png` — terminal chạy 4 lệnh kiểm tra (chỉ mã HTTP)
