# -*- coding: utf-8 -*-
"""
네이버 부동산 수집 엔진
"""
import asyncio, sys, time, logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SEARCH_CONFIGS, PLAYWRIGHT_HEADLESS, PLAYWRIGHT_TIMEOUT, PLAYWRIGHT_WAIT_SEC, PLAYWRIGHT_MAX_PAGES, LOG_DIR
from database import init_db, upsert_articles, mark_deleted, update_market_stats, log_run

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "collection.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


async def collect_one(config: dict) -> list:
    """단일 검색 조건으로 매물 수집 (전체 페이지 스크롤)"""
    from playwright.async_api import async_playwright

    articles = []
    seen_nos: set = set()
    is_more = [True]  # 리스트로 감싸서 클로저에서 변경 가능

    async def on_response(response):
        url = response.url
        if (response.status == 200
                and "new.land.naver.com/api/articles" in url
                and "clusters" not in url):
            try:
                data = await response.json()
                if "articleList" in data:
                    new_items = [
                        a for a in data["articleList"]
                        if a.get("articleNo") not in seen_nos
                    ]
                    for a in new_items:
                        seen_nos.add(a.get("articleNo"))
                    articles.extend(new_items)
                    is_more[0] = data.get("isMoreData", False)
                    log.info(
                        f"  API: +{len(new_items)}건 신규 "
                        f"(누적 {len(articles)}건, 더보기:{is_more[0]})"
                    )
            except Exception:
                pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ko-KR",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        page.on("response", on_response)

        # ① 쿠키 획득
        await page.goto("https://land.naver.com/", timeout=PLAYWRIGHT_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # ② 검색 URL 이동
        log.info(f"  수집 시작: {config['name']}")
        await page.goto(config["url"], timeout=PLAYWRIGHT_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(PLAYWRIGHT_WAIT_SEC)

        # ③ 스크롤로 추가 페이지 로드 (무한스크롤 대응)
        stall = 0
        for pg in range(2, PLAYWRIGHT_MAX_PAGES + 1):
            if not is_more[0]:
                log.info(f"  마지막 페이지 완료 ({pg - 1}페이지)")
                break
            prev = len(articles)

            # 매물 리스트 컨테이너 스크롤 (여러 셀렉터 순차 시도)
            await page.evaluate("""
                () => {
                    const sels = [
                        '.item_list', '._item_list', '._pcList',
                        '[class*="ItemList"]', '[class*="item_list"]',
                        '.article_list', '[class*="ArticleList"]',
                        '.lst_item', '[class*="resultArea"]',
                        '[class*="List_list"]', '[class*="ItemListContainer"]'
                    ];
                    for (const s of sels) {
                        const el = document.querySelector(s);
                        if (el && el.scrollHeight > el.clientHeight + 100) {
                            el.scrollTop = el.scrollHeight;
                            return s;
                        }
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                    return 'window';
                }
            """)
            await asyncio.sleep(2.5)

            if len(articles) == prev:
                stall += 1
                if stall >= 3:
                    log.info(f"  추가 로딩 없음 3회 연속 → 종료 (총 {len(articles)}건)")
                    break
            else:
                stall = 0

        await browser.close()

    log.info(f"  수집 완료: {len(articles)}건")
    return articles


def run_collection():
    """전체 수집 실행 (스케줄러에서 호출)"""
    init_db()
    total_new = total_updated = total_deleted = total_collected = 0
    start = time.time()

    for config in SEARCH_CONFIGS:
        if not config.get("active", True):
            continue

        log.info(f"[{config['name']}] 수집 시작")
        try:
            articles = asyncio.run(collect_one(config))
        except Exception as e:
            log.error(f"  수집 실패: {e}")
            log_run(config, 0, 0, 0, 0, "error", str(e), time.time() - start)
            continue

        # DB 저장
        counts = upsert_articles(articles, config)
        active_nos = {a["articleNo"] for a in articles if a.get("articleNo")}

        # 삭제 감지
        deleted = mark_deleted(active_nos, config["cortar_no"])

        # 시장 통계 갱신
        for rtype in config.get("real_estate_types", ["VL"]):
            update_market_stats(config["cortar_no"], rtype, config["trade_type"])

        n = len(articles)
        total_collected += n
        total_new += counts["new"]
        total_updated += counts["updated"]
        total_deleted += deleted

        log.info(
            f"  저장 완료 | 총:{n} 신규:{counts['new']} 변경:{counts['updated']} "
            f"삭제:{deleted} 동일:{counts['unchanged']}"
        )

    duration = round(time.time() - start, 1)
    log.info(f"전체 수집 완료 | {total_collected}건 | 소요 {duration}초")
    log_run(
        [c["name"] for c in SEARCH_CONFIGS if c.get("active")],
        total_collected, total_new, total_updated, total_deleted,
        "success", None, duration,
    )
    return total_collected, total_new, total_updated, total_deleted


if __name__ == "__main__":
    run_collection()
