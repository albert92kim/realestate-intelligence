# -*- coding: utf-8 -*-
"""
APScheduler 기반 자동 수집 스케줄러
실행: python scheduler.py
"""
import sys, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SCHEDULE_HOUR, SCHEDULE_MINUTE, LOG_DIR
from collector import run_collection

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler(timezone="Asia/Seoul")


@scheduler.scheduled_job("cron", hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE)
def daily_job():
    log.info(f"=== 정기 수집 시작 ({SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}) ===")
    try:
        total, new, updated, deleted = run_collection()
        log.info(f"=== 완료 | 총:{total} 신규:{new} 변경:{updated} 삭제:{deleted} ===")
    except Exception as e:
        log.error(f"=== 수집 오류: {e} ===")


if __name__ == "__main__":
    log.info(f"스케줄러 시작 — 매일 {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} 수집")
    log.info("즉시 1회 실행 후 스케줄 대기...")
    daily_job()   # 시작 시 즉시 1회 실행
    scheduler.start()
