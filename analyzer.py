# -*- coding: utf-8 -*-
"""
Gemini AI 분석 모듈
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import GEMINI_KEYS, GEMINI_MODEL
from database import get_conn


def get_active_listings(cortar_no: str = None, limit: int = 100) -> list:
    with get_conn() as conn:
        q = "SELECT * FROM properties WHERE is_active=1"
        params = []
        if cortar_no:
            q += " AND cortar_no=?"
            params.append(cortar_no)
        q += f" ORDER BY price_int ASC LIMIT {limit}"
        rows = conn.execute(q, params).fetchall()
        cols = [d[0] for d in conn.execute(q, params).description] if rows else []

    # fetchall 후 description이 사라짐 → 컬럼명 별도 조회
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM properties WHERE is_active=1 LIMIT 1")
        cols = [d[0] for d in cur.description]
        cur2 = conn.execute(
            "SELECT * FROM properties WHERE is_active=1" +
            (f" AND cortar_no='{cortar_no}'" if cortar_no else "") +
            f" ORDER BY price_int ASC LIMIT {limit}"
        )
        return [dict(zip(cols, row)) for row in cur2.fetchall()]


def get_market_summary(cortar_no: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT avg_price, median_price, min_price, max_price, total_count
            FROM market_stats
            WHERE cortar_no=? ORDER BY stat_date DESC LIMIT 1
        """, (cortar_no,)).fetchone()
    if row:
        return {"avg": row[0], "median": row[1], "min": row[2], "max": row[3], "count": row[4]}
    return {}


def call_gemini(prompt: str, key_index: int = 0) -> str:
    from google import genai
    key = GEMINI_KEYS[key_index % len(GEMINI_KEYS)]
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text


def detect_bargains(cortar_no: str) -> str:
    """급매 감지 분석"""
    listings = get_active_listings(cortar_no, 50)
    stats = get_market_summary(cortar_no)
    if not listings or not stats:
        return "데이터 없음"

    data_str = json.dumps([
        {"no": l["article_no"], "가격(만원)": l["price_int"],
         "면적": f"{l['area1']}/{l['area2']}",
         "층": l["floor_info"], "설명": l["description"]}
        for l in listings
    ], ensure_ascii=False)

    prompt = f"""
다음은 {listings[0].get('cortar_address', '해당 지역')} 매물 목록입니다.
평균가 {stats['avg']:,}만원, 중위가 {stats['median']:,}만원 기준으로
평균 대비 15% 이상 저렴한 급매 가능성 매물을 분석해줘.

매물 데이터:
{data_str}

출력 형식 (JSON):
{{
  "급매_매물": [
    {{"매물번호": "...", "가격": ..., "평균대비": "...", "이유": "..."}}
  ],
  "요약": "2~3문장 시장 코멘트"
}}
"""
    return call_gemini(prompt)


def market_trend_summary(cortar_no: str) -> str:
    """30일 시장 동향 요약"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT stat_date, avg_price, total_count, new_count, removed_count
            FROM market_stats WHERE cortar_no=?
            ORDER BY stat_date DESC LIMIT 30
        """, (cortar_no,)).fetchall()

    if not rows:
        return "데이터 없음 (수집 후 재시도)"

    data_str = "\n".join([
        f"{r[0]}: 평균가 {r[1]:,}만원, 매물 {r[2]}건, 신규 {r[3]}, 삭제 {r[4]}"
        for r in reversed(rows)
    ])
    prompt = f"""
다음은 최근 30일간 부동산 시장 데이터입니다.
1. 가격 추세 (상승/하락/보합, 구체적 수치)
2. 매물 소화 속도 (신규 vs 삭제 비율)
3. 투자 시사점 1~2가지
를 간결하게 한국어로 분석해줘.

데이터:
{data_str}
"""
    return call_gemini(prompt)


def keyword_analysis(cortar_no: str) -> str:
    """매물 설명 키워드 분석"""
    listings = get_active_listings(cortar_no, 100)
    descriptions = [l["description"] for l in listings if l.get("description")]

    prompt = f"""
다음은 부동산 매물 설명문 {len(descriptions)}건입니다.
아래 카테고리별 키워드 빈도와 시사점을 분석해줘:
- 재개발/재건축: 모아타운, 신통기획, 뉴타운, 사업시행인가
- 교통 호재: 역세권, GTX, 신설역
- 투자 유형: 갭투자, 급매, 세안고, 임차인있음
- 리스크: 소송, 가압류, 위반건축물

설명문:
{chr(10).join(descriptions[:50])}

결과를 JSON으로 반환:
{{"키워드_집계": {{}}, "주요_트렌드": "...", "주의_사항": "..."}}
"""
    return call_gemini(prompt)
