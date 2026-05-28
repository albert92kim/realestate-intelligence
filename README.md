# 네이버 부동산 인텔리전스

네이버 부동산에서 매물을 자동 수집하고, 지하철 거리·경사도·AI 분석을 더해 Streamlit 대시보드로 제공하는 시스템입니다.

**라이브 URL:** https://realestate-intelligence-aygy5yeh7wcraewk4op3hu.streamlit.app/

---

## 목적 및 범위

| 항목 | 내용 |
|------|------|
| **목적** | 특정 지역 매물의 가격 흐름·급매 감지·입지 분석을 자동화 |
| **수집 대상** | 네이버 부동산 (빌라·단독주택·다가구 매매/전세 등, 조건 설정 가능) |
| **분석 기능** | 급매 감지, 지하철 도보 거리, 경사도, Gemini AI 요약 |
| **배포 방식** | 로컬 PC 수집 → SQLite → GitHub push → Streamlit Cloud 자동 갱신 |

---

## 시스템 아키텍처

```
┌──────────────────────────────────────────┐
│  로컬 PC (Windows)                        │
│                                          │
│  collector.py (Playwright 브라우저)       │
│      │ 네이버 부동산 API 인터셉트           │
│      ▼                                   │
│  database.py → data/realestate.db        │
│      │                                   │
│  realestate_daily.ps1 (PowerShell)       │
│      │ git add / commit / push           │
│      ▼                                   │
│  GitHub (albert92kim/realestate-intel...) │
└──────────────────────────────────────────┘
         │  자동 반영 (~2분)
         ▼
┌──────────────────────────────────────────┐
│  Streamlit Community Cloud               │
│  app.py (읽기 전용 대시보드)               │
│  - 카카오 지도 (JS SDK)                   │
│  - 매물 표·차트·AI 분석                   │
└──────────────────────────────────────────┘
```

**핵심 설계 원칙:**
- Playwright는 서버리스 환경(Vercel·Netlify·Streamlit Cloud)에서 실행 불가 → 수집은 로컬 PC 전담
- 데이터 동기화는 SQLite 파일을 git으로 직접 push (API 서버 불필요)
- 클라우드에서는 `COLLECTION_AVAILABLE = False` 자동 감지 → 수집 버튼 숨김

---

## 파일 구조

```
realestate/
├── app.py              # Streamlit 대시보드 (메인 진입점)
├── collector.py        # 네이버 부동산 Playwright 수집 엔진
├── database.py         # SQLite CRUD (init, upsert, mark_deleted, stats)
├── enricher.py         # 위치 보강 (카카오 REST API, 고도, 경사도)
├── analyzer.py         # Gemini AI 분석
├── scheduler.py        # APScheduler 기반 정기 수집 (선택)
├── config.py           # 전역 설정 및 SEARCH_CONFIGS 정의
├── requirements.txt    # 클라우드 의존성 (Playwright 제외)
├── sync_to_cloud.bat   # git push 전용 (수동 동기화)
├── .gitignore
├── .streamlit/
│   ├── config.toml     # 테마 및 서버 설정
│   └── secrets.toml    # API 키 (gitignore 됨, 로컬 전용)
├── data/
│   ├── realestate.db   # SQLite DB (git 추적 O — 클라우드 동기화 수단)
│   └── .gitkeep
└── logs/
    └── collection.log  # 수집 로그 (gitignore 됨)

바탕화면/
├── collect_and_sync.bat    # Task Scheduler 진입점 (ASCII 이름, CRLF 안전)
└── realestate_daily.ps1    # 실제 수집+push 로직 (PowerShell, Unicode 경로 지원)
```

> `data/realestate.db`는 의도적으로 gitignore 하지 않습니다.  
> GitHub가 데이터 동기화 채널이기 때문입니다.

---

## 환경 설정

### 요구 사항

| 항목 | 버전 |
|------|------|
| Python | 3.13 |
| Playwright | 최신 (로컬 수집용) |

### 설치 순서

```powershell
# 1. 저장소 클론
git clone https://github.com/albert92kim/realestate-intelligence.git
cd realestate-intelligence

# 2. 의존성 설치 (로컬 실행 전체 기능)
pip install -r requirements.txt
pip install playwright apscheduler
playwright install chromium

# 3. 환경 변수 파일 생성 (아래 API 키 발급 후 작성)
#    위치: C:\Users\Albert\AI스크래핑\.env
```

### `.env` 파일 (로컬)

```env
# Kakao
KAKAO_API_KEY=KakaoAK_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KAKAO_JS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Gemini (최대 6개, 키가 많을수록 rate limit 여유)
GEMINI_API_KEY=AIza...
GEMINI_API_KEY2=AIza...
GEMINI_API_KEY3=AIza...
GEMINI_API_KEY4=AIza...
GEMINI_API_KEY5=AIza...
GEMINI_API_KEY6=AIza...
```

`config.py`는 `C:\Users\Albert\AI스크래핑\.env` → `realestate/.env` 순으로 자동 탐지합니다.

---

## API 키 발급 가이드

### Kakao REST API 키
1. https://developers.kakao.com → 로그인
2. 내 애플리케이션 → 애플리케이션 추가하기
3. **앱 키 탭** → **REST API 키** 복사
4. `.env`에 `KAKAO_API_KEY=KakaoAK_<복사한 키>` 입력

### Kakao JavaScript SDK 키
1. 같은 앱 → **앱 키 탭** → **JavaScript 키** 복사
2. **플랫폼** 탭 → **Web** → 사이트 도메인 등록
   - 로컬: `http://localhost:8501`
   - 클라우드: `https://realestate-intelligence-aygy5yeh7wcraewk4op3hu.streamlit.app`
3. `.env`에 `KAKAO_JS_KEY=<복사한 키>` 입력

> **중요:** Streamlit Cloud는 HTTPS 서버이므로 Kakao Maps SDK가 내부적으로 로드하는 `http://t1.daumcdn.net/...` 리소스가 Mixed Content로 차단됩니다. `app.py`의 `build_kakao_map()`에 `<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">` 태그가 이미 포함되어 이를 자동 해결합니다. **이 태그를 제거하면 클라우드에서 지도가 표시되지 않습니다.**

### Gemini API 키
1. https://aistudio.google.com/app/apikey
2. **Create API key** → 복사
3. rate limit 대비로 최대 6개까지 발급 가능 (각각 다른 구글 계정)

---

## 수집 조건 설정 (`config.py`)

```python
SEARCH_CONFIGS = [
    {
        "name": "화곡동_빌라단독_매매_방3_15년",   # 구분 이름 (DB 검색 조건 키)
        "cortar_no": "1150063000",               # 법정동 코드
        "cortar_address": "서울시 강서구 화곡동",
        "url": "https://new.land.naver.com/houses?...",  # 필터 적용된 URL 그대로 붙여넣기
        "real_estate_types": ["VL", "DDDGG"],    # 빌라, 단독/다가구
        "trade_type": "A1",                      # A1=매매 B1=전세 B2=월세
        "active": True,
    },
]
```

**URL 추출 방법:** land.naver.com에서 원하는 조건(지역·건물 유형·거래 유형·방 수·연식 등)을 필터로 설정한 뒤 주소창 URL을 복사합니다.

**주요 `real_estate_types` 코드:**

| 코드 | 유형 |
|------|------|
| `VL` | 빌라/연립/다세대 |
| `DDDGG` | 단독/다가구 |
| `APT` | 아파트 |
| `OPST` | 오피스텔 |

---

## 수집 메커니즘 (collector.py)

네이버 부동산은 API 직접 호출을 차단하므로 **Playwright로 실제 브라우저를 실행**해 네트워크 응답을 인터셉트합니다.

```
[Playwright 브라우저 실행]
    │
    ├─ ① land.naver.com 접속 (쿠키 획득)
    ├─ ② 검색 URL 이동
    ├─ ③ API 응답 인터셉트:
    │      URL: new.land.naver.com/api/articles
    │      조건: status=200, "clusters" 미포함
    │      파싱: articleList 배열, isMoreData 필드
    └─ ④ 페이지네이션:
           - fvwqf 버튼 클릭(다음 페이지) 방식
           - isMoreData=False 또는 버튼 없으면 종료
           - 최대 PLAYWRIGHT_MAX_PAGES(기본 20)회
```

**수집 성능:** 조건당 수분 소요. 매물 400건 기준 약 3~5분.

**수집 건수 관련 주의:** 매일 수집 결과가 동일한 건수(예: 400건)처럼 보여도 정상입니다.  
신규 등록 27건 + 거래완료 삭제 27건이 같은 날 일어나면 총계는 같습니다.  
실제 변동은 `price_history` 테이블(NEW/UP/DOWN/DELETED)에서 확인할 수 있습니다.

---

## 데이터베이스 스키마 (database.py)

### `properties` — 매물 원장

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `article_no` | TEXT PK | 네이버 매물 번호 |
| `real_estate_type` | TEXT | VL / DDDGG 등 |
| `trade_type` | TEXT | A1(매매) / B1(전세) 등 |
| `price_raw` | TEXT | 원본 가격 문자열 ("2억 5,500") |
| `price_int` | INTEGER | 만원 단위 정수 (25500) |
| `area1` / `area2` | REAL | 공급/전용 면적 (㎡) |
| `latitude` / `longitude` | REAL | WGS84 좌표 |
| `is_active` | INTEGER | 1=현재 매물, 0=삭제/거래완료 |
| `first_seen` / `last_seen` | TEXT | ISO8601 타임스탬프 |

### `price_history` — 가격 이력

| `change_type` 값 | 의미 |
|-----------------|------|
| `NEW` | 신규 등록 |
| `UP` | 가격 상승 |
| `DOWN` | 가격 하락 |
| `DELETED` | 매물 소멸 (거래 완료 추정) |

### `market_stats` — 일별 시장 통계

날짜 × 법정동 × 건물유형 × 거래유형 조합으로 일별 평균·중위·최소·최대 가격 저장.

### `collection_runs` — 수집 실행 기록

각 수집 실행마다 총건수·신규·변경·삭제 및 소요시간 기록.

---

## 대시보드 탭 구성 (app.py)

| 탭 | 기능 |
|----|------|
| **매물 목록** | 필터(건물유형·거래유형·가격범위·급매) + 지하철 거리 표 + 가격 분포 히스토그램 |
| **시장 동향** | 일별 평균가 추이 차트, 신규/삭제 건수 |
| **지도** | 카카오 지도 JS SDK — 매물 마커(색상: 🔴고가/🔵일반/🟢급매), 클러스터링, 지하철역 오버레이 |
| **AI 분석** | Gemini API로 선택 매물 또는 시장 전체 요약 |
| **수집 현황** | 수집 실행 기록, 오류 로그, 수동 수집 버튼(로컬 전용) |

### 급매 판정 기준 (`config.py`)

```python
BARGAIN_THRESHOLD = 0.15  # 평균 대비 15% 이하 → 급매 (초록 마커 + "급" 레이블)
```

---

## 카카오 지도 좌표 시스템 주의사항

**반드시 지킬 원칙:** 지하철역 마커는 Kakao JS SDK `Places.categorySearch('SW8')`로만 표시해야 합니다.

| 방법 | 문제 |
|------|------|
| OpenStreetMap(Folium) + 카카오 REST API 좌표 | 타일 DB ≠ 좌표 DB → 역이 학교·아파트 내부에 표시 |
| 카카오 JS 지도 + REST API 좌표 | 카카오 내부에서도 REST API DB ≠ Maps 타일 DB |
| **카카오 JS 지도 + JS SDK Places 검색** | **동일 DB 보장 → 정확한 위치** ✅ |

매물 좌표는 네이버 부동산 API가 제공하는 WGS84 좌표를 그대로 사용합니다. 카카오 지도 타일도 WGS84 기반이므로 별도 변환 불필요.

---

## 위치 보강 (enricher.py)

### 지하철역 거리 (표 표시용)
카카오 REST API (`dapi.kakao.com/v2/local/search/category.json?category_group_code=SW8`) 사용.  
API 키 없으면 강서구·양천구 주요 역 하드코딩 폴백으로 자동 전환.

### 역명 파싱
카카오가 반환하는 `"화곡역 5호선"` 형식을 `(역명, 호선)`으로 분리:
```python
def _parse_station_name(s: dict) -> tuple[str, str]:
    ...  # enricher.py 참조
```

### 고도·경사도
OpenTopoData SRTM30 무료 API (키 불필요).  
`estimate_slope()`: 5방향 고도를 한 번에 조회해 최대 경사도(%) 추정.

---

## 클라우드 배포 (Streamlit Community Cloud)

### 최초 배포 순서

1. GitHub 퍼블릭 저장소 필요 (무료 티어 조건)
2. https://streamlit.io/cloud → **New app** → GitHub 저장소 연결
3. **Main file path:** `app.py`
4. **Secrets** 탭에 API 키 입력 (TOML 형식):

```toml
KAKAO_API_KEY = "KakaoAK_xxx"
KAKAO_JS_KEY = "xxx"
GEMINI_API_KEY = "AIza..."
GEMINI_API_KEY2 = "AIza..."
# ... (최대 6개)
```

5. **Deploy!**

### 클라우드에서 secrets 작동 원리

`app.py` 상단의 브리지 코드가 `st.secrets` → `os.environ`으로 복사:
```python
for _k, _v in _st.secrets.items():
    os.environ.setdefault(str(_k), str(_v))
```
`config.py`는 `os.environ`에서 키를 읽으므로 로컬(`.env`)과 클라우드(`st.secrets`) 모두 동일하게 작동합니다.

---

## 자동화 (Windows Task Scheduler)

### 등록된 스케줄

- **작업 이름:** `RealEstate_Auto_Sync`
- **실행 시각:** 매일 07:00
- **실행 파일:** `C:\Users\Albert\Desktop\collect_and_sync.bat`

### 스크립트 구조

```
바탕화면/
├── collect_and_sync.bat    ← Task Scheduler가 실행하는 진입점 (ASCII 이름)
└── realestate_daily.ps1    ← 실제 수집+push 로직 (PowerShell)
```

`collect_and_sync.bat` 내용 (단 1줄):
```batch
@echo off
powershell -ExecutionPolicy Bypass -File "C:\Users\Albert\Desktop\realestate_daily.ps1"
```

`realestate_daily.ps1` 실행 흐름:
```
[1/3] Python collector.py 실행 (수집)
   ↓ 성공
[2/3] git add data\realestate.db → git commit → git push
   ↓ 성공
[3/3] 완료 메시지
실패 시: 오류 메시지 출력
로그: C:\Users\Albert\Desktop\realestate_log.txt
```

> **BAT 파일 인코딩 주의:** Windows cmd.exe는 CP949(EUC-KR)로 BAT 파일을 읽습니다.  
> Write/Edit 도구가 생성한 파일은 UTF-8이므로, 한국어 경로가 포함된 BAT 파일은  
> 문자 깨짐으로 실행 즉시 닫힙니다. 따라서 진입점은 ASCII 이름+내용의 BAT,  
> 실제 로직은 Unicode를 완전 지원하는 PowerShell(.ps1)로 분리되어 있습니다.

### Task Scheduler 재등록 (필요 시)

```powershell
schtasks /delete /tn "RealEstate_Auto_Sync" /f

schtasks /create /tn "RealEstate_Auto_Sync" `
  /tr "\"C:\Users\Albert\Desktop\collect_and_sync.bat\"" `
  /sc DAILY /st 07:00 /ru "%USERNAME%" /f
```

---

## 데이터 동기화 워크플로우

```
수집 완료
   │
   ▼
git add data\realestate.db
git commit -m "Auto update YYYY-MM-DD"
git push
   │
   ▼ (GitHub → Streamlit Cloud, ~2분)
대시보드 자동 갱신
```

**수동 동기화 (수집 없이 push만):**
```powershell
cd "C:\Users\Albert\AI스크래핑\realestate"
.\sync_to_cloud.bat
```

**Git 인증:** PAT(Personal Access Token)를 remote URL에 내장:
```
https://albert92kim:<TOKEN>@github.com/albert92kim/realestate-intelligence.git
```

---

## 로컬 실행

```powershell
cd "C:\Users\Albert\AI스크래핑\realestate"

# 대시보드만 보기 (수집 없이)
streamlit run app.py

# 수동 수집 1회
python collector.py

# 정기 스케줄러 실행 (시작 즉시 1회 + 매일 07:00)
python scheduler.py
```

---

## 트러블슈팅

### 카카오 지도가 클라우드에서 안 보임 (Mixed Content)

**증상:** 로컬에서는 지도가 나오는데 Streamlit Cloud에서만 빈 화면  
**원인:** Kakao Maps SDK가 내부적으로 `http://t1.daumcdn.net/...`(HTTP)을 로드하는데, HTTPS 페이지에서는 Mixed Content로 차단  
**해결:** `app.py`의 `build_kakao_map()` HTML에 이 태그가 있어야 합니다:
```html
<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
```
이 태그가 HTTP 요청을 HTTPS로 자동 업그레이드해 차단을 우회합니다.

**DevTools에서 확인 방법 (F12 → Console):**
```
Mixed Content: ... requested an insecure script 'http://t1.daumcdn.net/...'
```
이 에러가 보이면 위 meta 태그를 추가하면 됩니다.

### 카카오 지도 — 도메인 미등록 오류

**증상:** `CATCH: kakao.maps.LatLng is not a constructor` 또는 SDK 로드 실패  
**해결 순서:**
1. Streamlit Cloud Secrets에 `KAKAO_JS_KEY` 등록 여부 확인
2. Kakao 개발자 콘솔 → 플랫폼 → Web에 도메인 등록:
   - `http://localhost:8501`
   - `https://realestate-intelligence-aygy5yeh7wcraewk4op3hu.streamlit.app`

### 지하철역이 잘못된 위치에 표시

`app.py`의 `build_kakao_map()`이 `Places.categorySearch('SW8')`를 사용하는지 확인.  
카카오 REST API 좌표를 JS 지도에 직접 찍으면 위치 오류 발생 (카카오 내부 DB 불일치).

### BAT 파일 실행 즉시 닫힘

한국어 경로가 포함된 BAT을 UTF-8로 저장하면 CP949 디코딩 실패로 즉시 종료됩니다.  
**해결:** 진입점 BAT은 ASCII만 사용, 실제 로직은 PowerShell(.ps1)로 분리합니다.  
현재 설정: `collect_and_sync.bat` → `realestate_daily.ps1` 구조로 이미 해결됨.

로그 확인: `C:\Users\Albert\Desktop\realestate_log.txt`

### 수집 건수가 매일 같음 (예: 400건)

**정상 동작입니다.** 시장에서 신규 등록과 거래완료가 비슷한 수로 발생하면 총 활성 매물 수는 유지됩니다.  
실제 변동 내역은 `price_history` 테이블의 `change_type`(NEW/UP/DOWN/DELETED)로 확인하세요.

### git push 403 / Permission denied

```powershell
# 자격 증명 초기화
cmdkey /delete:git:https://github.com

# remote URL 재설정 (PAT 포함)
git remote set-url origin https://albert92kim:<TOKEN>@github.com/albert92kim/realestate-intelligence.git

# git 사용자 확인
git config user.name "albert92kim"
git config user.email "klitpub88@gmail.com"
```

### git push 후 "nothing to commit"

`data/realestate.db`의 수정 시각이 이전 commit 이후와 같으면 git이 변경으로 인식하지 않습니다.  
collector.py가 실제로 DB를 업데이트했다면 git이 diff를 감지합니다 (SQLite delete journal 모드 사용 중).  
수집이 정상 실행됐는지 로그(`realestate_log.txt`)를 확인하세요.

### 수집이 안 됨 (0건)

- 네이버 부동산 URL이 유효한지 확인: 실제 브라우저에서 열어 매물이 보이는지 확인
- `PLAYWRIGHT_WAIT_SEC` 값을 늘려보세요 (기본 5초 → 10초)
- 네이버가 봇 감지 강화 시 `headless=False`로 전환해 테스트

### Streamlit Cloud에서 SQLite 데이터 없음

클라우드는 DB를 직접 수정하지 않습니다. 로컬에서 수집 후 push가 필요합니다:
```powershell
python collector.py
git add data\realestate.db
git commit -m "Add data"
git push
```

---

## 향후 개선 계획

| 항목 | 설명 |
|------|------|
| 검색 조건 UI | 대시보드에서 SEARCH_CONFIGS를 동적으로 추가/변경 |
| 다중 지역 지원 | SEARCH_CONFIGS에 여러 지역 동시 수집 |
| 알림 기능 | 급매 등록 시 카카오 알림톡 또는 이메일 발송 |
| 가격 예측 | 가격 이력 기반 ML 모델 |
| 사용자 인증 | Streamlit Cloud 유료 플랜의 프라이빗 앱 + 구글 로그인 |
| 수집 주기 다양화 | 급매 탐지는 3시간마다, 일반 통계는 1일 1회 분리 |

---

## 계정 및 접근 정보

| 항목 | 값 |
|------|-----|
| GitHub 계정 | `albert92kim` |
| GitHub 저장소 | `albert92kim/realestate-intelligence` |
| Streamlit Cloud | https://share.streamlit.io (albert92kim 계정) |
| 수집 PC | Windows 11, `C:\Users\Albert\AI스크래핑\realestate\` |

---

## 주요 변경 이력

| 날짜 | 변경 내용 |
|------|-----------|
| 2026-05-28 | **카카오 지도 Mixed Content 수정** — `upgrade-insecure-requests` CSP 메타 태그 추가. Streamlit Cloud(HTTPS)에서 Kakao SDK 서브 스크립트(HTTP)가 차단되는 문제 해결 |
| 2026-05-28 | **BAT 파일 인코딩 수정** — 한국어 경로가 포함된 BAT의 CP949/UTF-8 불일치 문제 해결. `collect_and_sync.bat`(ASCII 진입점) → `realestate_daily.ps1`(PowerShell) 구조로 변경 |
| 2026-05-28 | 수집 페이지네이션 방식 변경: `window.scrollTo` → `fvwqf 버튼 클릭` |
| 2026-05-28 | 수집 방식 변경: curl_cffi → Playwright 브라우저 인터셉트 |
