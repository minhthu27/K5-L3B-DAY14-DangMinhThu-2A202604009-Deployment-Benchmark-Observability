# Benchmark & Observability Report — Day 14

**Họ tên:** Đặng Minh Thu (2A202604009)
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 Home, Docker Desktop (WSL2), Python 3.11.9. Bước 1 (develop) chạy agent bằng Python trên Windows; Bước 2 (production) chạy bằng Docker Compose project `k5-day14-observability`. Máy dùng cho cả load generator lẫn agent nên số tuyệt đối chỉ có giá trị so sánh tương đối.

> Mọi con số dưới đây lấy từ `reports/*.json`, `benchmark-results/*.csv`, ảnh trong `screenshots/` và log Docker. Số không có file chứng từ (thời gian firing của alert) lấy từ script điều khiển thí nghiệm, ghi rõ ở mục 4.2.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~120–180 ms; 500 ms cho phép ~3 lần thời gian bình thường. Dùng p95 (không dùng avg) vì avg che tail latency. |
| Error rate `/ask` | < 2 % | Mock LLM có chủ đích 1 % lỗi upstream (`MOCK_ERROR_RATE=0.01`); 2 % là mức chấp nhận được khi chưa có retry. Alert đặt lỏng hơn (5 %) để tránh alert fatigue. |
| Accuracy trên golden dataset | ≥ 95 % | Dataset chỉ có 23 câu nên 1 câu sai = 4,3 điểm %. CI gate đang đặt `--min-accuracy 1.0` vì v2 đã đạt 23/23 và không được phép regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Agent v2, `--requests 300`, một process uvicorn, file: `reports/load_v2_c{1,10,50,100}.json`.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (p95 ≤ 500 ms, err ≤ 2 %) |
|---|---|---|---|---|---|---|
| 1 | 4,32 | 202,8 | 236,1 | 1684,5 | 0,67 % | ✅ PASS |
| 10 | 35,82 | 197,8 | 448,7 | 1693,9 | 1,67 % | ✅ PASS |
| 50 | 99,13 | 208,6 | 524,6 | 1732,8 | 1,00 % | ❌ FAIL (p95) |
| 100 | 39,13 | 824,9 | 5520,6 | 5654,6 | 2,67 % | ❌ FAIL (p95 và error rate) |

**Nhận xét:** RPS **không** tăng tuyến tính.
- Từ 1 → 10 → 50 RPS tăng gần tuyến tính (4,3 → 35,8 → 99,1) vì mỗi request chủ yếu *chờ* LLM giả lập (`asyncio.sleep`), nên một process async phục vụ được nhiều request chồng nhau. Đây là workload I/O-bound.
- Từ 50 lên 100 RPS **giảm** (99 → 39) và p95 nhảy từ 0,5 s lên 5,5 s: đã vượt điểm bão hoà. Với 1 process uvicorn, event loop + hàng đợi kết nối trở thành nút thắt, request xếp hàng nên p50 cũng tăng gấp 4 (209 → 825 ms). Tôi chưa cô lập được nguyên nhân chính xác (khả năng cao là giới hạn của một process cộng với load generator chạy chung máy Windows), nên đây là giả thuyết, không phải kết luận đã kiểm chứng.
- Ngưỡng dùng được để vận hành theo SLO của agent này nằm quanh concurrency 10–50 trên máy này.

### 2.2 Tail latency (concurrency 20, 300 request)

Mỗi lần restart agent v2 với `MOCK_SLOW_RATE` khác nhau (file `reports/load_v2_slow_{0,0.03,0.1}.json`).

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | RPS | SLO |
|---|---|---|---|---|---|
| 0 | 211,9 | 446,4 | 481,2 | 92,02 | ✅ |
| 0.03 (mặc định) | 231,6 | 467,5 | 1648,3 | 64,41 | ✅ |
| 0.1 | 330,4 | 1682,6 | 1726,6 | 49,58 | ❌ (p95) |

**Nhận xét:** Chỉ số nhạy nhất là **p99**, rồi tới p95 khi tỉ lệ chậm vượt 5 %. Khi 3 % request chậm thêm 1,5 s, avg chỉ tăng 9 % (211,9 → 231,6) nhưng p99 tăng 3,4 lần (481 → 1648 ms). Ở 10 % thì p95 cũng bị kéo lên 1,68 s trong khi avg mới 330 ms. Request chậm là thiểu số nên avg bị "pha loãng": 3 % × 1,5 s chỉ cộng ~45 ms vào avg, nhưng 1 trong 33 người dùng phải chờ ~1,7 s. Vì thế SLO phải đặt theo percentile (p95/p99), không theo average. (Lưu ý các lần chạy có dao động ngẫu nhiên: lần `0.03` này cũng cho p95 chạm 467 ms gần ngưỡng 500 ms.)

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Golden dataset 23 câu. File: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4,3 % (1/23) | 91,3 % (21/23) | **100 % (23/23)** |
| Avg tokens / câu | 56,9 | 109,1 | 114,6 |
| Tổng cost (USD) | 0,000401 | 0,000762 | 0,000799 |
| Cost / câu đúng (USD) | 0,00040095 | 0,00003627 | 0,00003472 |
| Latency p95 trong eval (ms) | 1515,7 | 234,3 | 242,2 |
| Quality gate | ❌ FAIL (so với ngưỡng 80 %) | ✅ PASS (ngưỡng 80 %) | ✅ PASS (ngưỡng 100 %, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` (KB không có tài liệu nào về HPA) | Thêm vào `KNOWLEDGE_BASE` một entry với từ khoá `["hpa", "kubernetes"]`, nội dung nêu rõ CPU, memory và custom metrics |
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm entry với từ khoá `["jwt", "api key"]`, nội dung nêu token, chữ ký, thời gian hết hạn |

Đã kiểm tra bằng grep trước khi sửa rằng không câu nào khác trong dataset chứa `jwt`, `api key`, `kubernetes`, `hpa`, nên hai entry mới không cướp kết quả retrieval của câu khác. Kết quả: lần eval cuối "Câu được cải thiện: 2, Câu bị regression: 0". Cùng nội dung đã được chép sang `production/utils/mock_llm.py` để stack Docker cũng đạt 100 %.

**Quality gate trong CI:** `run_eval.py` thoát với exit code 1 khi accuracy < `--min-accuracy` hoặc có regression so với `--baseline`. Đã kiểm chứng: chạy v1 với `--baseline reports/eval_v2.json` trả **exit code 1**; chạy v2 sau sửa KB với `--min-accuracy 1.0` trả **exit code 0**. Job CI nằm ở `.github/workflows/eval-gate.yml`: bật agent v2 trong runner, chạy `run_eval.py --min-accuracy 1.0 --baseline reports/eval_v2_fixed.json`; bước nào exit ≠ 0 thì job fail, và khi đặt job `eval` làm required status check trong branch protection thì PR không merge được.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:** v2 dùng nhiều token hơn ~1,9 lần mỗi câu (109,1 so với 56,9) vì prompt có thêm context retrieval, nên tổng cost cao gấp ~1,9 lần. Nhưng accuracy tăng từ 4,3 % lên 91,3 %, nên **cost trên mỗi câu đúng giảm ~11 lần** (4,0e-4 → 3,6e-5 USD). Một câu rẻ nhưng sai thì không có giá trị, vì vậy "cost / câu đúng" mới là số công bằng để so hai phiên bản. Về latency, retrieval thêm ~20 ms mỗi request (span `agent.retrieve_context` ≈ 26 ms trong trace) — không đáng kể so với ~170–200 ms của LLM. (p95 của v1 trong eval cao hơn v2 là do v1 vô tình trúng vài request chậm ngẫu nhiên trong mẫu 23 câu; mẫu quá nhỏ để kết luận latency — đúng như cảnh báo của README.)

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png` (Golden Signals: error rate 18,58 %, p95 1,89 s, 2 instance up; chụp lúc thí nghiệm A+B đang chạy với 15 user Locust nền)
- [x] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (span `chat mock-llm-small` có event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với 2 alert đang **firing**: `screenshots/prometheus-alert-firing.png` (`AgentHighErrorRate` và `AgentHighLatencyP95`)

Unit test alert: `promtool test rules alert_rules_test.yml` → `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống"

Cách đo: 2 instance agent, Locust headless 15 user (~10 req/s) chạy nền suốt thí nghiệm (cố ý dùng 15 user, không phải 30, vì với 30 user baseline đã sát ngưỡng cost $2/giờ và sẽ làm alert C firing sẵn). Thời gian tính từ lúc `docker compose up -d` (áp `.env` mới) trả về tới khi `/api/v1/alerts` của Prometheus báo `firing`; giữa các thí nghiệm trả `.env` về mặc định và chờ mọi alert về inactive. Mỗi thí nghiệm chạy **một lần**, nên số giây có sai lệch vài giây.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 90,5 s (pending sau 30,2 s) | Stat "Error rate" (đỏ), "Requests/s theo status code" (xuất hiện series 503) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 144,7 s (pending sau 24,1 s) | "Latency /ask p50/p95/p99" (p95 và p99 vượt đường 1 s, avg tăng ít hơn) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 162,8 s (pending sau 42,2 s) | "Cost burn rate (USD/giờ)" và "LLM latency p95 theo model" |
| D | `docker pause` agent-1 | `AgentInstanceDown` | 39,2 s (pending sau 9,0 s) | Stat "Instances up" (còn 1), bảng version |
| E | `AGENT_VERSION=v1` | **Không có** (kiểm tra sau 150 s: danh sách alert rỗng) | — | Không panel hạ tầng nào đỏ |
| A+B | `MOCK_ERROR_RATE=0.2` và `MOCK_SLOW_RATE=0.3` cùng lúc | `AgentHighErrorRate` (90,4 s) và `AgentHighLatencyP95` (147,8 s) | cả hai firing đồng thời → ảnh `prometheus-alert-firing.png` | Cả hai stat đỏ trong `grafana-dashboard.png` |

Giải thích vì sao thời gian dài hơn `for:` trong rule: alert dùng `rate(...[1m])` nên cần ~30–60 s dữ liệu mới phản ánh thay đổi (pending), rồi còn phải giữ đúng điều kiện suốt `for:` (1 phút cho A, 2 phút cho B và C). D nhanh nhất vì `up == 0` có hiệu lực ngay ở lần scrape (5 s) kế tiếp, chỉ chờ `for: 30s`.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Metric hạ tầng (latency, error rate, up, cost) đo xem agent *có chạy* không, không đo *câu trả lời có đúng không*. v1 trả lời nhanh, rẻ, HTTP 200, nên mọi panel vẫn xanh trong khi accuracy tụt từ 91 % xuống 4 %. Cần các tầng giám sát chất lượng: (1) **eval liên tục** chạy golden dataset theo lịch (hoặc canary) với quality gate trong CI/CD và cảnh báo khi accuracy tụt; (2) metric nghiệp vụ như retrieval hit ratio (panel có sẵn trên dashboard; với v1 không có bước retrieval), tỉ lệ "không biết/trả lời chung chung"; (3) feedback người dùng (thumbs up/down) và sampling log để chấm tay hoặc LLM-as-judge; (4) cảnh báo khi `agent_info{version}` thay đổi bất ngờ so với bản dự kiến deploy. Trong lần chạy này, tôi chỉ **xác nhận được** điểm đầu tiên bằng đo đạc (v1 bị bắt bởi eval: 4,3 %, gate FAIL); phần còn lại là đề xuất, tôi không dựng thử.

### 4.3 Debug bằng trace

Trace chậm nhất trong cửa sổ 20 phút cuối (trace còn log tương ứng):

- `trace_id`: `95f66491ed055ab5f5f5ea268a0edcf6`
- Tổng thời gian: **1725,8 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` — **1695,8 ms (98,3 %)**; `agent.retrieve_context` chỉ 25,9 ms. Tức là chậm do LLM upstream (request rơi vào nhóm "slow" của mock), không phải code của agent.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T08:13:44.057623+00:00", "level": "INFO", "service": "observable-agent", "instance": "8fa14f1e3f56", "event": "llm_call", "trace_id": "95f66491ed055ab5f5f5ea268a0edcf6", "span_id": "806b98a1ea41d716", "request_id": "3b8270dc6bac", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 75, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1694.7}
{"ts": "2026-11-26T08:13:44.058522+00:00", "level": "INFO", "service": "observable-agent", "instance": "8fa14f1e3f56", "event": "http_request", "trace_id": "95f66491ed055ab5f5f5ea268a0edcf6", "span_id": "806b98a1ea41d716", "request_id": "3b8270dc6bac", "method": "POST", "route": "/ask", "status": 200, "ms": 1724.8}
```

Trace lỗi: `064def79ade626aab286d8b176c0a061` (112,1 ms). Span `chat mock-llm-small` có status error và event `exception` với thông báo `LLMError: Upstream LLM error: 503 Service Unavailable (mock)`; lỗi lan lên `agent.run` và `POST /ask` (HTTP 503). Log tương ứng:

```json
{"ts": "2026-11-26T08:13:50.861805+00:00", "level": "INFO", "service": "observable-agent", "instance": "8ff9c61d7df9", "event": "llm_error", "trace_id": "064def79ade626aab286d8b176c0a061", "span_id": "b8e21b663a110bf0", "request_id": "0622836abcc1", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T08:13:50.862193+00:00", "level": "INFO", "service": "observable-agent", "instance": "8ff9c61d7df9", "event": "http_request", "trace_id": "064def79ade626aab286d8b176c0a061", "span_id": "b8e21b663a110bf0", "request_id": "0622836abcc1", "method": "POST", "route": "/ask", "status": 503, "ms": 111.4}
```

### 4.4 Trả lời Exercise 7.1 và 7.4

**7.1 — loại metric** (trích từ `/metrics` của agent v2 sau 1 request): Counter `http_requests_total{method="POST",route="/ask",status="200"} 1.0`; Gauge `agent_in_flight_requests 0.0`; Histogram `http_request_duration_seconds_bucket{le="0.2",...}` (cùng `_sum`, `_count`). **Label `route`:** nếu dùng URL thật, mỗi URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`...) tạo ra một tổ hợp label mới = một time series mới; bot quét hàng nghìn URL → hàng nghìn series (nhân với số bucket của histogram), Prometheus tốn RAM/CPU và có thể sập; dùng `route.path` (template) hoặc `unmatched` giữ số series cố định. **Metric thêm:** `agent_question_length_chars` (Histogram, bucket 20…2000) trong `develop/app.py`; dùng Histogram thay vì label `length=...` vì độ dài có vô số giá trị. Đã kiểm tra: sau 1 request `agent_question_length_chars_count 1.0`.

**7.4 (số liệu lấy từ ảnh Grafana lúc A+B đang chạy, nên là trạng thái bị phá hệ thống, không phải baseline):**
1. p95 = 1,89 s; avg thấp hơn nhiều (đường avg dưới 1 s trên biểu đồ latency, p99 gần 2 s). Khoảng cách lớn giữa avg và p95/p99 cho biết latency phân bố lệch đuôi dài: đa số request nhanh, một nhóm thiểu số rất chậm.
2. Nginx chia đều: hai series "Requests/s theo instance" (172.19.0.4 và 172.19.0.8) bám sát nhau ≈ 4 req/s mỗi bên (round-robin); chỉ lệch khi tôi `docker pause` một instance trong thí nghiệm D.
3. Input tokens/s lớn hơn output: input gồm system prompt + context retrieval + câu hỏi (≈ 70–90 token), còn output chỉ là câu trả lời ngắn (≈ 37–55 token). Ví dụ một request v2: input 75, output 37.
4. `curl http://localhost:8080/metrics` qua Nginx trả **404** vì `nginx.conf` có `location = /metrics { return 404; }` — metric lộ thông tin hệ thống/lưu lượng nên chỉ Prometheus scrape trực tiếp trong mạng nội bộ Docker.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Locust `-u 100 -r 10 -t 2m --no-deps`, file `benchmark-results/scale_{1,3}_stats.csv`. Số instance thực chạy được xác minh bằng `docker ps` ngay trước mỗi lượt (1 và 3).

> Lưu ý phương pháp: `docker compose run locust` mặc định khởi động lại service `agent` theo `deploy.replicas: 2`, làm lượt "1 instance" thực ra chạy 2. Tôi phát hiện ở lần chạy đầu, bỏ kết quả đó và chạy lại với `--no-deps`. Số liệu bên dưới là của lần chạy lại.

Dòng `POST /ask` trong CSV:

| Số instance | Requests | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|---|
| 1 | 7122 | 59,99 | 200 | 350 | 1700 | 77 (1,08 %) |
| 3 | 7051 | 59,37 | 200 | 250 | 1700 | 72 (1,02 %) |

(Dòng Aggregated gồm cả `/health`: 1 instance — 65,49 RPS, p95 330 ms; 3 instance — 65,18 RPS, p95 240 ms.)

**Giải thích kết quả:**
- **RPS gần như không đổi** (~60). Nguyên nhân là kịch bản Locust: mỗi user chờ `between(0.5, 2)` giây giữa hai lần gọi, nên 100 user sinh tối đa ≈ 100 / (1,25 + ~0,2) ≈ 69 req/s, và 1 instance đã đáp ứng đủ. Load generator mới là nút thắt, không phải agent; scale ngang chỉ có lợi khi tải vượt công suất 1 instance.
- **p95 cải thiện** 350 → 250 ms (aggregated 330 → 240 ms). Giả thuyết hợp lý (chưa cô lập bằng thí nghiệm riêng): khi 100 user đến dồn dập, một instance giới hạn 0,5 CPU phải xếp hàng một số request, còn 3 instance chia bớt hàng đợi. Chỉ một lần chạy mỗi cấu hình nên chênh 100 ms có thể một phần là nhiễu.
- **p99 không đổi (1700 ms)** và failures ≈ 1 % không đổi: cả hai đến từ mock LLM (3 % request chậm +1,5 s, 1 % lỗi 503), nằm ở **phía upstream LLM**. Thêm instance không sửa được lỗi hay độ chậm của dịch vụ phụ thuộc. Nút thắt của tail latency là LLM (xem panel LLM latency và span `chat mock-llm-small` trong Jaeger). Muốn giảm cần timeout/retry/hedging, cache, hoặc model/nhà cung cấp nhanh hơn, không phải thêm replica.

---

## 6. Kết luận

- 3 điều đã học về benchmark & observability:
  1. **Đo bằng percentile, không bằng trung bình**: với 3 % request chậm, avg chỉ tăng 9 % nhưng p99 tăng 3,4 lần; SLO và alert phải theo p95/p99.
  2. **Mỗi loại benchmark trả lời một câu hỏi khác nhau**: load test cho biết nhanh/ổn định, eval cho biết đúng/sai (v1 4,3 % vs v2 100 %), còn dashboard hạ tầng xanh vẫn có thể che một agent trả lời sai (thí nghiệm E). So sánh phiên bản nên dùng cost / câu đúng.
  3. **Kết quả đo phải kiểm tra phương pháp**: lần đầu "scale 1" thực chất chạy 2 instance, và benchmark scale bị chặn bởi load generator chứ không phải agent. Metrics chỉ nói *có vấn đề*, trace chỉ ra *bước nào* (98 % thời gian ở span LLM), log (qua `trace_id`) cho biết *chuyện gì xảy ra*.
- Nếu đưa agent này lên production thật, sẽ thêm: (a) eval định kỳ/online với alert khi accuracy tụt, (b) alert ở tầng load balancer/synthetic check (vì lỗi 504 của Nginx không xuất hiện trong metric của agent), (c) metric và alert cho Redis (latency, memory, kết nối) và cho rate-limit/cost-guard (số 429, 402), (d) SLO burn-rate alert nhiều cửa sổ thay vì ngưỡng cố định, (e) sampling trace (vd giữ 10 % + 100 % trace lỗi/chậm) để kiểm soát chi phí khi traffic lớn.
