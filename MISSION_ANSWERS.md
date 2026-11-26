# Mission Answers — Day 14

**Họ tên:** Đặng Minh Thu (2A202604009) · **Lớp:** K5-L3B · **Ngày làm:** 2026-11-26

> Môi trường: Windows 11 + Docker Desktop (WSL2). Phần cần SIGTERM (5.2, `check_production_ready.py`) chạy trong **container Linux** (Python 3.11 + docker CLI + redis-server, mount docker socket), vì Python Windows không gửi được SIGTERM (xem mục *Lưu ý* số 2 trong README). Các output bên dưới là output thật; token đã che.

---

## Part 1 — Localhost vs Production

### Exercise 1.1 — Anti-pattern trong `01-localhost-vs-production/develop/app.py`

| # | Dòng | Vấn đề | Hậu quả |
|---|---|---|---|
| 1 | 17 | `OPENAI_API_KEY = "sk-hardcoded-..."` hardcode secret | Push lên GitHub là lộ key |
| 2 | 18 | `DATABASE_URL = "postgresql://admin:password123@localhost..."` hardcode mật khẩu | Lộ credential, không đổi được giữa dev/staging/prod |
| 3 | 21–22 | `DEBUG = True`, `MAX_TOKENS = 500` cứng trong code | Muốn đổi phải sửa code và build lại |
| 4 | 33–38 | Dùng `print()`, không có log có cấu trúc | Khó lọc/tìm kiếm trong log aggregator, không có level |
| 5 | 34 | `print(f"Using key: {OPENAI_API_KEY}")` — **log ra secret** | Secret nằm trong log (đã thấy tận mắt ở 1.2) |
| 6 | 42–43 | Không có `/health`, `/ready` | Platform không biết khi nào restart / route traffic |
| 7 | 51 | `host="localhost"` | Trong container/cloud không nhận được kết nối từ ngoài |
| 8 | 52 | `port=8000` cứng, không đọc `PORT` | Railway/Render inject `PORT` → app lắng nghe sai cổng |
| 9 | 53 | `reload=True` | Chế độ dev (theo dõi file, process con) trên production |
| 10 | — | Không xử lý shutdown, không xác thực, nhận `question` qua query string | Cắt ngang request khi deploy; ai cũng gọi được; câu hỏi lộ trong URL/log |

### Exercise 1.2 — Chạy bản develop

```
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity      # bản develop không nhận JSON, chỉ nhận query
$ curl -o /dev/null -w "%{http_code}" localhost:8000/health
404                                     # không có health check
```

Log của server (đúng như dự đoán — lộ secret):
```
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
```
**Quan sát:** "Chạy được" nhưng chưa production-ready: lộ secret trong log, không có health check, bind `localhost`.

### Exercise 1.3 — So sánh develop vs production

Chạy bản production (`production/app.py`): `/health` → 200 `{"status":"ok","uptime_seconds":5.5,...}`, `/ready` → 200 `{"ready":true}`, `POST /ask` (JSON) → 200.

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (dòng 17–22) | Env vars qua `config.py` (`os.getenv`, có `validate()`) | Cùng một image chạy ở dev/staging/prod; secret không nằm trong git (12-Factor III) |
| Secrets | Hardcode + in ra log | Chỉ đọc từ env, không log secret | Chống lộ key |
| Host / Port | `localhost`, `8000` cứng | `0.0.0.0`, `PORT` từ env | Container và PaaS (Railway/Render) inject cổng qua `PORT` |
| Health check | Không có | `/health` (liveness) + `/ready` (readiness) | Platform restart khi chết, ngừng route khi chưa sẵn sàng |
| Logging | `print()` | Log JSON có `event`, không log secret | Máy đọc được, đưa vào Datadog/Loki được |
| Shutdown | Đột ngột (reload=True, không lifespan) | `lifespan` + bắt SIGTERM, graceful | Không mất request đang xử lý khi deploy/scale-down |
| Reload | `reload=True` luôn bật | Chỉ khi `DEBUG=true` | Tránh hành vi dev trên production |
| CORS | Không | `allow_origins` cấu hình được | Kiểm soát origin được gọi |

**Hiểu:** hardcode secret nguy hiểm vì lịch sử git giữ mãi (xoá file không đủ); health check cho phép nền tảng tự phục hồi; graceful shutdown để không cắt ngang request người dùng.

---

## Part 2 — Docker

### Exercise 2.1 — Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (bản đầy đủ, nặng).
2. **Working directory:** `/app`.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo layer. Dependencies ít đổi hơn code; copy `requirements.txt` + `pip install` trước thì khi chỉ sửa code, layer cài đặt được dùng lại từ cache, build nhanh hơn nhiều.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/đối số **mặc định**, bị thay thế khi truyền lệnh vào `docker run <image> <cmd>`. `ENTRYPOINT` là chương trình cố định của container; đối số của `docker run` được **nối thêm** vào nó (chỉ đổi được bằng `--entrypoint`). Thường dùng ENTRYPOINT cho executable, CMD cho đối số mặc định.

### Exercise 2.2 — Build & run

```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=What+is+Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3 — Multi-stage

- **Stage 1 (builder):** `python:3.11-slim` + cài `gcc`, `libpq-dev` + `pip install --user` vào `/root/.local`. Không dùng để deploy.
- **Stage 2 (runtime):** `python:3.11-slim`, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` và mã nguồn, có `HEALTHCHECK`, chạy `uvicorn --workers 2`.
- **Vì sao nhỏ hơn:** trình biên dịch/build tools và cache của pip nằm lại ở stage builder, không vào image cuối; base `slim` thay cho bản đầy đủ.

**Kích thước đo được** (`docker images my-agent`, Docker 29.2.1):

| Image | Content size | Disk usage |
|---|---|---|
| `my-agent:develop` | **426 MB** | 1,67 GB |
| `my-agent:advanced` | **57,4 MB** | 240 MB |

Giảm **86,5 %** (content size: 426 → 57,4 MB); theo disk usage giảm 85,6 %.

### Exercise 2.4 — Docker Compose stack

`touch .env.local` rồi `docker compose -p k5-day14-docker up -d --build` trong `02-docker/production/`. Cả 4 service lên và healthy:

```
SERVICE   STATUS                    PORTS
agent     Up 26 seconds (healthy)   8000/tcp
nginx     Up 25 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    Up 36 seconds (healthy)   6333-6334/tcp
redis     Up 36 seconds (healthy)   6379/tcp
```

Sơ đồ:

```
Client ──► nginx :80/:443 ──► agent :8000 ──┬─► redis  :6379  (session, rate limit)
 (duy nhất nginx publish port)             └─► qdrant :6333  (vector DB cho RAG)
                       tất cả cùng mạng bridge nội bộ `internal`
```
Agent không publish cổng; chỉ nginx lộ ra ngoài. `depends_on ... condition: service_healthy` đảm bảo redis và qdrant sẵn sàng trước agent. Các service gọi nhau bằng tên service qua DNS của Docker (`redis://redis:6379`, `http://qdrant:6333`).

Test qua Nginx:
```
$ curl -s -w ' [%{http_code}]' http://localhost/health
{"status":"ok","uptime_seconds":24.3,"version":"2.0.0",...} [200]
$ curl -s -w ' [%{http_code}]' -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."} [200]
```
Đã `docker compose down` sau khi xong.

---

## Part 3 — Cloud Deployment

Deploy chính trên **Railway** (Exercise 3.1), deploy luôn agent Part 6 trong `06-lab-complete/` (do chủ bài chạy lệnh Railway CLI; kiểm tra từ bên ngoài do tôi chạy). Chi tiết, biến môi trường và các lỗi gặp phải: [DEPLOYMENT.md](DEPLOYMENT.md).

**URL public:** https://k5-agent-production.up.railway.app

| Kiểm tra | Kết quả |
|---|---|
| `GET /health` | 200 |
| `GET /ready` | 200 (Redis Railway đã nối) |
| `POST /ask` không key | 401 |
| `POST /ask` có `X-API-Key` | 200 |

`AGENT_API_KEY`, `REDIS_URL`, `ENVIRONMENT`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD` đặt bằng `railway variables set`, không nằm trong code. Xem log bằng `railway logs --service k5-agent`.

### So sánh `railway.toml` và `render.yaml` của agent Part 6 (`06-lab-complete/`)

| Khía cạnh | `railway.toml` | `render.yaml` | Vì sao khác |
|---|---|---|---|
| Kiểu file | Chỉ cấu hình **build + deploy** của một service | **Blueprint** (Infrastructure-as-Code) khai báo cả **nhiều service** | Render mô tả cả hạ tầng trong một file; Railway tạo thêm dịch vụ (Redis) bằng dashboard/CLI |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath: ./Dockerfile` | Cùng dùng Dockerfile multi-stage; chỉ khác cú pháp |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` | Cả hai dùng `/health` (liveness) để quyết định deploy thành công/restart |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Render tự restart, không khai báo ở đây | Railway cho chỉnh chính sách restart trong file |
| Biến môi trường | **Không** nằm trong file; đặt bằng `railway variables set ...` hoặc dashboard | Khai báo trong `envVars`: `generateValue: true` cho `AGENT_API_KEY`, `fromService` cho `REDIS_URL` | Render sinh secret và nối service giúp bạn; Railway đặt tay, `REDIS_URL` dùng reference tới Redis service |
| Redis | Tạo Redis service riêng rồi đặt `REDIS_URL` | Khai báo `type: keyvalue` ngay trong file, `REDIS_URL` lấy từ `connectionString` | Render quản lý được cả phụ thuộc trong một file |
| Cổng | Railway inject `PORT` | Render inject `PORT` | CMD của Dockerfile dùng `${PORT:-8000}` nên chạy được ở cả hai |

Secret không nằm trong code ở cả hai: Railway dùng biến đặt trên nền tảng, Render dùng `generateValue`/`sync: false`.

### Exercise 3.3 — Cloud Run (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` định nghĩa pipeline CI/CD chạy khi push `main`, gồm 4 bước tuần tự (`waitFor`): (1) **test** — cài requirements và chạy `pytest` trong `python:3.11-slim`, fail thì dừng; (2) **build** — `docker build` gắn tag `$COMMIT_SHA` và `latest`, dùng `--cache-from` để tận dụng layer cache; (3) **push** — đẩy mọi tag lên Container Registry; (4) **deploy** — `gcloud run deploy` image theo `$COMMIT_SHA` lên `asia-southeast1` với `--min-instances=1` (tránh cold start), `--max-instances=10`, 512Mi/1 CPU, timeout 60s, env `ENVIRONMENT=production` và secret `OPENAI_API_KEY` lấy từ Secret Manager (`--set-secrets`). `service.yaml` là bản Knative khai báo cùng cấu hình dưới dạng IaC (`gcloud run services replace`): autoscaling min 1 / max 10, `containerConcurrency: 80`, tài nguyên, env/secret từ `secretKeyRef`, `livenessProbe` `/health` và `startupProbe` `/ready`. Chưa deploy thật (không cần tài khoản GCP theo đề).

---

## Part 4 — API Security

### Exercise 4.1 — API Key (`04-api-gateway/develop`)

- **Key được check ở đâu:** hàm dependency `verify_api_key` (dòng 39–54), gắn vào `/ask` bằng `Depends(verify_api_key)`; đọc header `X-API-Key`, so sánh với `AGENT_API_KEY` (env).
- **Sai key:** thiếu key → **401**, key sai → **403** (bản develop tách hai trường hợp).
- **Rotate key:** đổi biến môi trường `AGENT_API_KEY` rồi restart (không cần sửa code); để không downtime nên cho phép nhiều key cùng hợp lệ trong thời gian chuyển đổi.

```
$ AGENT_API_KEY=secret-key-123 python app.py
$ curl -i -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
$ curl -i ... -H "X-API-Key: wrong"
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}
$ curl -i ... -H "X-API-Key: secret-key-123"
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock)..."}
```

### Exercise 4.2 — JWT (`04-api-gateway/production`)

Luồng: `POST /auth/token` kiểm tra user/password → server ký JWT (HS256, payload `sub`, `role`, `iat`, `exp` = 60 phút) → client gửi `Authorization: Bearer <token>` → server verify chữ ký + hạn, không cần tra DB (stateless). Hết hạn → 401, token sai → 403.

```
$ curl -i -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -s -X POST localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token":"eyJhbGciOiJIUzI1NiIs...<đã che>"}

$ curl -i -X POST localhost:8000/ask -H "Authorization: Bearer <TOKEN-đã-che>" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! ...","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

### Exercise 4.3 — Rate limiting

- **Algorithm:** Sliding Window Counter (mỗi user một `deque` timestamp; bỏ timestamp cũ hơn 60 s; đếm).
- **Limit:** user **10 req/phút**, admin **100 req/phút**.
- **Bypass cho admin:** không bypass hoàn toàn; `role == "admin"` (trong JWT) dùng `rate_limiter_admin` (100 req/phút).

Vòng lặp 15 request liên tiếp bằng token `student` (mã HTTP + đầu body):
```
1–9 : HTTP/1.1 200 OK
10  : HTTP/1.1 429 Too Many Requests {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":55}}
11–15: HTTP/1.1 429 Too Many Requests ... retry_after_seconds 54 → 53
Header khi bị chặn: x-ratelimit-limit: 10 · x-ratelimit-remaining: 0 · retry-after: 53
```
(Request đầu tiên của 4.2 đã dùng 1 slot nên 9 request của vòng lặp còn trả 200, đúng 10 request trong cửa sổ.)

### Exercise 4.4 — Cost guard

Cost guard của bản production (in-memory): ngân sách **$1/ngày/user** (vượt → **402**) và **$10/ngày toàn cục** (vượt → 503), cảnh báo ở 80 %. Cost mỗi request = `input_tokens/1000 × 0,00015 + output_tokens/1000 × 0,0006`. `/me/usage` báo `requests=10, cost_usd=0.000191, budget_remaining_usd=0.999809`.

Bản tôi làm cho agent Part 6 (`06-lab-complete/app/cost_guard.py`) lưu trong **Redis** để nhiều worker/instance dùng chung và không mất khi restart: khoá theo ngày `cost:day:YYYY-MM-DD` và theo tháng `cost:month:YYYY-MM` (UTC), cộng bằng `INCRBYFLOAT` kèm `EXPIRE` (3 ngày / 35 ngày). `check_budget()` chạy **trước** khi gọi LLM, đọc cả hai khoá bằng `MGET`; chạm `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD` → 402; nếu Redis lỗi thì trả 503 (fail-closed, không để chi tiêu không kiểm soát). `record_cost()` chạy sau khi gọi LLM. Script chấm xác nhận: budget 0,000001 USD → 402 ngay request thứ 1.

**Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ **tốc độ** (chống spam/DoS, 429); cost guard bảo vệ **tiền** (một người gọi chậm nhưng prompt rất dài vẫn đốt budget mà không chạm rate limit; ngược lại nhiều request rẻ có thể chạm rate limit trước khi tốn tiền).

---

## Part 5 — Scaling & Reliability

### Exercise 5.1 — Health checks

- **`/health` (liveness):** luôn 200 khi process còn chạy (kèm uptime, kiểm tra memory bằng psutil); nếu fail nền tảng **restart** container.
- **`/ready` (readiness):** 200 khi đã khởi động xong và dependencies sẵn sàng, **503** khi đang khởi động/shutdown hoặc mất Redis; nếu fail load balancer **ngừng route** traffic nhưng không restart. Đây là lý do `/health` không phụ thuộc Redis còn `/ready` thì có (đúng yêu cầu CP5).

```
/health 200 {"status":"ok","uptime_seconds":3.6,"version":"1.0.0","checks":{"memory":{"status":"ok","used_percent":6.5}}}
/ready  200 {"ready":true,"in_flight_requests":1}
```

### Exercise 5.2 — Graceful shutdown (chạy trong container Linux)

Gửi một request `/ask` rồi gửi `SIGTERM` ngay sau 50 ms:
```
in-flight request -> 200 {"answer":"Tôi là AI agent được deploy lên cloud...."}
app exit code=0
INFO:     Shutting down
INFO:     "POST /ask?question=Long+task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
... 🔄 Graceful shutdown initiated...
... ✅ Shutdown complete
INFO:     Application shutdown complete.
```
Request đang chạy vẫn hoàn thành (200), lifespan shutdown chạy, process thoát với code 0. Quy trình: ngừng nhận kết nối mới → chờ in-flight → đóng kết nối → thoát. Lưu ý: nếu tự đăng ký `signal.signal(SIGTERM, ...)` phải giữ hành vi của uvicorn, nếu không process không bao giờ tắt (cảnh báo trong đề).

### Exercise 5.3 — Stateless

Anti-pattern: `conversation_history = {}` trong RAM — mỗi instance có bộ nhớ riêng, request kế tiếp trúng instance khác sẽ "mất" lịch sử; instance chết là mất hết. Đúng cách: lưu history/session trong Redis (`history:{session_id}`), mọi instance đọc chung → scale ngang được. Bản `05-scaling-reliability/production/app.py` làm đúng như vậy (`save_session`, `load_session`, `append_to_history` đều qua Redis); agent Part 6 cũng để rate-limit và cost state trong Redis.

### Exercise 5.4 — Load balancing (3 instance)

```
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
agent-1, agent-2, agent-3, redis, nginx — tất cả healthy
10 request POST /chat:   4 × instance-964e0f · 3 × instance-d0fc2c · 3 × instance-fee055
```
Nginx phân phối round-robin gần đều qua 3 instance.

### Exercise 5.5 — Test stateless

```
$ python test_stateless.py
Session ID: 50ea989f-...        (5 câu hỏi trong cùng một session)
Request 1: [instance-964e0f]   Request 2: [instance-d0fc2c]   Request 3: [instance-fee055]
Request 4: [instance-964e0f]   Request 5: [instance-d0fc2c]
Instances used: {'instance-964e0f', 'instance-fee055', 'instance-d0fc2c'}
Total messages: 10
✅ Session history preserved across all instances via Redis!
```
5 câu do 3 instance khác nhau xử lý nhưng lịch sử đủ 10 tin nhắn (5 user + 5 assistant) vì state ở Redis. Thử thêm (ngoài script, vì script không tự tắt instance): `docker stop` agent-1 rồi chạy lại: chỉ còn 2 instance phục vụ, vẫn thành công, history vẫn 10 tin nhắn (của session mới). Xong đã `docker compose -p k5-day14-scaling down`.

---

## Part 6 — Final Project

Code trong `06-lab-complete/` (`app/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`). Điểm thiết kế chính:

- **Auth:** `APIKeyHeader("X-API-Key")` + `secrets.compare_digest`; thiếu/sai → 401.
- **Rate limit:** Redis sorted set (sliding window 60 s) theo `sha256(api_key)`, vượt → 429 + `Retry-After`; state nằm trong Redis nên sống sót qua restart và dùng chung giữa các worker.
- **Cost guard:** Redis `INCRBYFLOAT` theo ngày/tháng → 402.
- **`/health` luôn 200; `/ready`** ping Redis, 503 khi lỗi. Redis client tạo lazy nên app khởi động được khi chưa có Redis.
- **Log JSON** từng dòng (`ts`, `lvl`, `event`, …); handler lỗi chung trả `{"detail":"Internal server error"}`, 422 gọn — không lộ stack trace.
- **Graceful shutdown:** dựa vào uvicorn (SIGTERM → drain request → `lifespan` shutdown), `--timeout-graceful-shutdown 8`; uvicorn là PID 1 nhờ `exec`.
- **Docker:** multi-stage `python:3.11-slim` (venv), user non-root, `HEALTHCHECK`, `CMD` dùng `${PORT:-8000}`; image **63 MB**.

Lệnh chạy: **trong container Linux** có Docker (vì Windows không gửi được SIGTERM), mount cả repo để `.gitignore` ở thư mục cha được nhìn thấy:
```
docker run --rm --network host -v /var/run/docker.sock:/var/run/docker.sock \
  -v <repo>:/repo -w /repo/06-lab-complete <image Python+docker CLI+redis-server> python check_production_ready.py
```
Output (phần *Checklist Deliverable*):

```
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Ghi chú trung thực: `check_production_ready.py` **không bị sửa**. Việc chạy trong container Linux là cách vượt giới hạn Windows nêu trong README thay cho WSL2 (máy này chỉ có distro `docker-desktop`, không có Ubuntu). Lab Coach nên chạy lại trên máy của họ.

---

## Part 7 — Benchmark & Observability

Toàn bộ nằm trong [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md), kèm `reports/`, `benchmark-results/` và 4 ảnh Part 7 trong `screenshots/`. Hai sửa đổi so với code mẫu: (1) thêm 2 entry `KNOWLEDGE_BASE` (HPA, JWT) ở cả `develop/` và `production/utils/mock_llm.py`; (2) sửa `production/Dockerfile` thêm `ENV PYTHONUSERBASE=/home/agent/.local` vì bản gốc làm container agent crash-loop (`ModuleNotFoundError: No module named 'uvicorn'`: user `agent` có HOME=`/app` nên Python không thấy package đã cài `--user`). Thêm metric `agent_question_length_chars` (Exercise 7.1) và job CI `.github/workflows/eval-gate.yml` (Exercise 7.3).

---

## AI log (khai báo sử dụng AI)

- **Công cụ:** Claude Code (mô hình Sonnet 5.5) thực hiện chạy các bài tập Part 1–5, chạy benchmark/thí nghiệm Part 7.
- **Tôi (AI) tự chạy và kiểm chứng:** mọi output trong file này lấy từ lần chạy thật trên máy trong ngày 2026-11-26. Kết quả `PASS 12/12` do chính script chấm in ra.
- **Phần cần con người:** deploy lên Railway do chủ bài chạy lệnh trên tài khoản của mình (tôi hướng dẫn và chẩn đoán lỗi từ log, rồi kiểm tra URL public từ bên ngoài); chủ bài tự chụp 3 ảnh deploy (`dashboard.png`, `running.png`, `test.png`) và tự chạy lệnh có API key. Xem DEPLOYMENT.md.
- **Chủ bài cần tự rà soát** để hiểu và bảo vệ được bài (RULES.md về dùng AI): đọc lại mã `06-lab-complete/app/*`, hiểu vì sao `/health` khác `/ready`, cách sliding window dùng Redis, và các số trong BENCHMARK_REPORT.
