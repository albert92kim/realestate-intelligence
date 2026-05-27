# -*- coding: utf-8 -*-
"""
네이버 부동산 수집 시스템 - 설정
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR  = BASE_DIR / "logs"
EXPORT_DIR = BASE_DIR / "exports"

DB_PATH  = DATA_DIR / "realestate.db"

# .env 자동 탐지 (로컬: 상위 폴더 / 클라우드: 없어도 동작)
for _env in [BASE_DIR.parent / ".env", BASE_DIR / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

# Kakao API 키
KAKAO_API_KEY = os.environ.get("KAKAO_API_KEY", "")
KAKAO_JS_KEY  = os.environ.get("KAKAO_JS_KEY",  "")

# Gemini API 키 (AI 분석용)
GEMINI_KEYS = [
    os.environ.get("GEMINI_API_KEY"),
    os.environ.get("GEMINI_API_KEY2"),
    os.environ.get("GEMINI_API_KEY3"),
    os.environ.get("GEMINI_API_KEY4"),
    os.environ.get("GEMINI_API_KEY5"),
    os.environ.get("GEMINI_API_KEY6"),
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]
GEMINI_MODEL = "google_genai/gemini-2.5-flash"

# ──────────────────────────────────────────────
# 수집 검색 조건 목록
# URL: land.naver.com에서 조건 적용 후 복사
# ──────────────────────────────────────────────
SEARCH_CONFIGS = [
    {
        "name": "화곡동_빌라단독_매매_방3_15년",
        "cortar_no": "1150063000",
        "cortar_address": "서울시 강서구 화곡동",
        "url": "https://new.land.naver.com/houses?ms=2AKRHp,3zca1D,15&a=DDDGG:VL&b=A1&e=RETAIL&j=15&q=THREEROOM",
        "real_estate_types": ["VL", "DDDGG"],
        "trade_type": "A1",
        "active": True,
    },
    # 추가 검색 조건 예시 (active=False → 비활성)
    # {
    #     "name": "화곡동_빌라단독_전세",
    #     "cortar_no": "1150063000",
    #     "cortar_address": "서울시 강서구 화곡동",
    #     "url": "https://new.land.naver.com/houses?ms=2AKRHp,3zca1D,15&a=DDDGG:VL&b=B1&e=RETAIL",
    #     "real_estate_types": ["VL", "DDDGG"],
    #     "trade_type": "B1",
    #     "active": False,
    # },
]

# 스케줄 설정
SCHEDULE_HOUR   = 7    # 매일 수집 시각 (24시 기준)
SCHEDULE_MINUTE = 0

# 급매 감지 기준 (평균 대비 N% 이하)
BARGAIN_THRESHOLD = 0.15   # 15% 이하 = 급매

# Playwright 설정
PLAYWRIGHT_HEADLESS  = True
PLAYWRIGHT_TIMEOUT   = 60000  # ms
PLAYWRIGHT_WAIT_SEC  = 5      # API 응답 대기 초
PLAYWRIGHT_MAX_PAGES = 20     # 최대 스크롤 페이지 수 (1페이지=약 20건)
