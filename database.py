# -*- coding: utf-8 -*-
"""
SQLite DB 초기화 및 CRUD
"""
import sqlite3, json
from datetime import datetime
from pathlib import Path
from config import DB_PATH


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS properties (
            article_no        TEXT PRIMARY KEY,
            real_estate_type  TEXT,
            type_name         TEXT,
            trade_type        TEXT,
            trade_name        TEXT,
            price_raw         TEXT,
            price_int         INTEGER,
            area1             REAL,
            area2             REAL,
            floor_info        TEXT,
            direction         TEXT,
            build_year        INTEGER,
            description       TEXT,
            tag_list          TEXT,
            latitude          REAL,
            longitude         REAL,
            cortar_no         TEXT,
            cortar_address    TEXT,
            building_name     TEXT,
            realtor_name      TEXT,
            article_url       TEXT,
            confirm_date      TEXT,
            first_seen        TEXT,
            last_seen         TEXT,
            is_active         INTEGER DEFAULT 1,
            search_condition  TEXT
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            article_no    TEXT NOT NULL,
            price_raw     TEXT,
            price_int     INTEGER,
            changed_at    TEXT,
            change_type   TEXT,
            change_amount INTEGER
        );

        CREATE TABLE IF NOT EXISTS market_stats (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_date        TEXT,
            cortar_no        TEXT,
            real_estate_type TEXT,
            trade_type       TEXT,
            total_count      INTEGER,
            avg_price        INTEGER,
            median_price     INTEGER,
            min_price        INTEGER,
            max_price        INTEGER,
            new_count        INTEGER,
            removed_count    INTEGER,
            UNIQUE(stat_date, cortar_no, real_estate_type, trade_type)
        );

        CREATE TABLE IF NOT EXISTS collection_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at        TEXT,
            search_json   TEXT,
            total         INTEGER,
            new_cnt       INTEGER,
            updated_cnt   INTEGER,
            deleted_cnt   INTEGER,
            status        TEXT,
            error_msg     TEXT,
            duration_sec  REAL
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            article_no  TEXT PRIMARY KEY,
            memo        TEXT DEFAULT '',
            added_at    TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_properties_cortar ON properties(cortar_no);
        CREATE INDEX IF NOT EXISTS idx_properties_active ON properties(is_active);
        CREATE INDEX IF NOT EXISTS idx_price_history_no ON price_history(article_no);
        CREATE INDEX IF NOT EXISTS idx_market_stats_date ON market_stats(stat_date, cortar_no);
        CREATE INDEX IF NOT EXISTS idx_watchlist_no ON watchlist(article_no);
        """)
    print("DB 초기화 완료:", DB_PATH)


def parse_price(price_raw: str) -> int:
    """'2억 5,500' → 25500 (만원)"""
    if not price_raw:
        return 0
    p = price_raw.replace(",", "").replace(" ", "")
    total = 0
    if "억" in p:
        parts = p.split("억")
        total += int(parts[0]) * 10000
        remainder = parts[1].strip() if parts[1].strip() else "0"
        if remainder:
            total += int(remainder)
    else:
        total = int(p) if p.isdigit() else 0
    return total


def upsert_articles(articles: list, search_config: dict) -> dict:
    """매물 목록을 DB에 저장. 신규/변경/삭제 카운트 반환."""
    now = datetime.now().isoformat()
    counts = {"new": 0, "updated": 0, "unchanged": 0}

    with get_conn() as conn:
        for a in articles:
            no = a.get("articleNo", "")
            if not no:
                continue

            price_raw = a.get("dealOrWarrantPrc", "") or a.get("warrantPrc", "")
            price_int = parse_price(price_raw)
            tags = json.dumps(a.get("tagList", []), ensure_ascii=False)

            existing = conn.execute(
                "SELECT price_int, is_active FROM properties WHERE article_no=?", (no,)
            ).fetchone()

            row = (
                no,
                a.get("realEstateTypeCode", ""),
                a.get("realEstateTypeName", ""),
                a.get("tradeTypeCode", ""),
                a.get("tradeTypeName", ""),
                price_raw,
                price_int,
                a.get("area1"),
                a.get("area2"),
                a.get("floorInfo", ""),
                a.get("direction", ""),
                a.get("buildYear"),
                a.get("articleFeatureDesc", ""),
                tags,
                a.get("latitude"),
                a.get("longitude"),
                search_config.get("cortar_no", ""),
                search_config.get("cortar_address", ""),
                a.get("buildingName", "") or a.get("articleName", ""),
                a.get("realtorName", "") or a.get("cpName", ""),
                a.get("cpPcArticleUrl", ""),
                a.get("articleConfirmYmd", ""),
                now,  # first_seen (INSERT 시만 사용)
                now,  # last_seen
                1,
                search_config.get("name", ""),
            )

            if existing is None:
                # 신규
                conn.execute("""
                    INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, row)
                conn.execute("""
                    INSERT INTO price_history (article_no, price_raw, price_int, changed_at, change_type, change_amount)
                    VALUES (?,?,?,?,?,?)
                """, (no, price_raw, price_int, now, "NEW", 0))
                counts["new"] += 1

            else:
                old_price, old_active = existing
                change = price_int - old_price if old_price else 0

                # last_seen + is_active 갱신
                conn.execute("""
                    UPDATE properties SET price_raw=?, price_int=?, last_seen=?, is_active=1,
                        description=?, confirm_date=?, latitude=?, longitude=?
                    WHERE article_no=?
                """, (price_raw, price_int,
                      now,
                      a.get("articleFeatureDesc", ""),
                      a.get("articleConfirmYmd", ""),
                      a.get("latitude"), a.get("longitude"),
                      no))

                if change != 0:
                    change_type = "UP" if change > 0 else "DOWN"
                    conn.execute("""
                        INSERT INTO price_history (article_no, price_raw, price_int, changed_at, change_type, change_amount)
                        VALUES (?,?,?,?,?,?)
                    """, (no, price_raw, price_int, now, change_type, change))
                    counts["updated"] += 1
                else:
                    counts["unchanged"] += 1

    return counts


def mark_deleted(active_nos: set, cortar_no: str) -> int:
    """현재 수집 목록에 없는 기존 매물 → 삭제/거래 처리"""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT article_no FROM properties WHERE cortar_no=? AND is_active=1", (cortar_no,)
        ).fetchall()
        deleted = 0
        for (no,) in rows:
            if no not in active_nos:
                conn.execute(
                    "UPDATE properties SET is_active=0, last_seen=? WHERE article_no=?", (now, no)
                )
                conn.execute("""
                    INSERT INTO price_history (article_no, price_raw, price_int, changed_at, change_type, change_amount)
                    VALUES (?,?,?,?,?,?)
                """, (no, "", 0, now, "DELETED", 0))
                deleted += 1
    return deleted


def update_market_stats(cortar_no: str, real_estate_type: str, trade_type: str):
    """오늘 시장 통계 갱신"""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT price_int FROM properties
            WHERE cortar_no=? AND real_estate_type=? AND trade_type=? AND is_active=1 AND price_int > 0
        """, (cortar_no, real_estate_type, trade_type)).fetchall()

        if not rows:
            return

        prices = sorted([r[0] for r in rows])
        n = len(prices)
        avg = int(sum(prices) / n)
        median = prices[n // 2]

        # 신규/삭제 건수 (오늘)
        new_cnt = conn.execute("""
            SELECT COUNT(*) FROM price_history ph
            JOIN properties p ON ph.article_no = p.article_no
            WHERE p.cortar_no=? AND p.real_estate_type=? AND p.trade_type=?
              AND ph.change_type='NEW' AND ph.changed_at LIKE ?
        """, (cortar_no, real_estate_type, trade_type, f"{today}%")).fetchone()[0]

        del_cnt = conn.execute("""
            SELECT COUNT(*) FROM price_history ph
            JOIN properties p ON ph.article_no = p.article_no
            WHERE p.cortar_no=? AND p.real_estate_type=? AND p.trade_type=?
              AND ph.change_type='DELETED' AND ph.changed_at LIKE ?
        """, (cortar_no, real_estate_type, trade_type, f"{today}%")).fetchone()[0]

        conn.execute("""
            INSERT OR REPLACE INTO market_stats
            (stat_date, cortar_no, real_estate_type, trade_type,
             total_count, avg_price, median_price, min_price, max_price, new_count, removed_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (today, cortar_no, real_estate_type, trade_type,
              n, avg, median, prices[0], prices[-1], new_cnt, del_cnt))


def log_run(search_json, total, new_cnt, updated_cnt, deleted_cnt, status, error_msg, duration):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO collection_runs
            (run_at, search_json, total, new_cnt, updated_cnt, deleted_cnt, status, error_msg, duration_sec)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (datetime.now().isoformat(), json.dumps(search_json, ensure_ascii=False),
              total, new_cnt, updated_cnt, deleted_cnt, status, error_msg, duration))


# ── 관심 매물 CRUD ─────────────────────────────────────

def get_watched_nos() -> set:
    with get_conn() as conn:
        rows = conn.execute("SELECT article_no FROM watchlist").fetchall()
    return {r[0] for r in rows}


def get_watchlist_df():
    import pandas as _pd
    with get_conn() as conn:
        cur = conn.execute("""
            SELECT w.article_no, w.memo, w.added_at, w.updated_at,
                   p.type_name, p.trade_name, p.price_raw, p.price_int,
                   p.area2, p.floor_info, p.build_year, p.description,
                   p.latitude, p.longitude, p.building_name, p.realtor_name,
                   p.article_url, p.is_active, p.first_seen, p.cortar_address, p.direction
            FROM watchlist w
            LEFT JOIN properties p ON w.article_no = p.article_no
            ORDER BY w.added_at DESC
        """)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return _pd.DataFrame(rows, columns=cols) if rows else _pd.DataFrame()


def add_to_watchlist(article_no: str, memo: str = "") -> None:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO watchlist (article_no, memo, added_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (article_no, memo, now, now))


def remove_from_watchlist(article_no: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE article_no=?", (article_no,))


def update_watchlist_memo(article_no: str, memo: str) -> None:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET memo=?, updated_at=? WHERE article_no=?",
            (memo, now, article_no)
        )


if __name__ == "__main__":
    init_db()
