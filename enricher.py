# -*- coding: utf-8 -*-
"""
위치 데이터 보강 모듈

우선순위:
  1) 카카오 로컬 API  — 가장 정확, KAKAO_API_KEY 있으면 자동 사용
  2) 하드코딩 폴백    — API 키 없을 때 강서구/양천구 주요 역만 제공

설정: .env 에 KAKAO_API_KEY=KakaoAK_xxx 추가

카카오 무료 키 발급 (3분):
  https://developers.kakao.com → 내 애플리케이션 → 새 앱 생성 → REST API 키 복사
"""
import math, os, logging

log = logging.getLogger(__name__)

# ── 폴백용 하드코딩 역 데이터 (OSM Nominatim + 지리검증, 강서구/양천구) ─────
# 카카오 API 키가 없을 때만 사용
_FALLBACK_STATIONS = [
    {"name": "화곡",      "line": "5호선",      "lat": 37.548787, "lon": 126.850326},
    {"name": "우장산",    "line": "5호선",      "lat": 37.553574, "lon": 126.843847},
    {"name": "까치산",    "line": "2·5호선",    "lat": 37.543990, "lon": 126.837519},
    {"name": "발산",      "line": "5호선",      "lat": 37.558531, "lon": 126.839017},
    {"name": "마곡",      "line": "5호선",      "lat": 37.558900, "lon": 126.828200},
    {"name": "공항시장",  "line": "5호선",      "lat": 37.559095, "lon": 126.808516},
    {"name": "개화산",    "line": "5호선",      "lat": 37.565302, "lon": 126.820665},
    {"name": "방화",      "line": "5호선",      "lat": 37.578640, "lon": 126.813200},
    {"name": "양천구청",  "line": "5호선",      "lat": 37.538051, "lon": 126.857020},
    {"name": "오목교",    "line": "5호선",      "lat": 37.539696, "lon": 126.866116},
    {"name": "목동",      "line": "5호선",      "lat": 37.538660, "lon": 126.875219},
    {"name": "마곡나루",  "line": "공항·9호선", "lat": 37.570390, "lon": 126.827840},
    {"name": "가양",      "line": "9호선",      "lat": 37.561142, "lon": 126.858000},
    {"name": "증미",      "line": "9호선",      "lat": 37.557510, "lon": 126.861818},
    {"name": "등촌",      "line": "9호선",      "lat": 37.551152, "lon": 126.864574},
    {"name": "양천향교",  "line": "9호선",      "lat": 37.533617, "lon": 126.854097},
    {"name": "신정네거리","line": "2호선",       "lat": 37.532994, "lon": 126.850212},
    {"name": "까치울",    "line": "2호선",       "lat": 37.535820, "lon": 126.839840},
]

# 카카오 API로 받아온 역을 캐시 (세션 내 1회 조회)
_kakao_station_cache: dict = {}   # key: (lat_r, lon_r) → list


# ════════════════════════════════════════════════════════
#  카카오 로컬 API
# ════════════════════════════════════════════════════════

def _kakao_key() -> str:
    from config import GEMINI_KEYS  # noqa — just to trigger dotenv load
    return os.environ.get("KAKAO_API_KEY", "")


def _kakao_category(lat: float, lon: float,
                    category: str, radius: int = 3000) -> list:
    """
    카카오 로컬 카테고리 검색 (반경 radius 미터)
    category: SW8=지하철역  BS8=버스정류장  BK9=은행 …
    반환: [{"name": ..., "lat": ..., "lon": ..., "distance": ...}, ...]
    """
    key = _kakao_key()
    if not key:
        return []
    try:
        import requests
        all_docs = []
        for page in range(1, 4):           # 최대 3페이지 (45개)
            r = requests.get(
                "https://dapi.kakao.com/v2/local/search/category.json",
                params={"category_group_code": category,
                        "x": lon, "y": lat,
                        "radius": radius, "sort": "distance",
                        "size": 15, "page": page},
                headers={"Authorization": f"KakaoAK {key}"},
                timeout=6,
            )
            data = r.json()
            docs = data.get("documents", [])
            all_docs.extend(docs)
            if data.get("meta", {}).get("is_end", True):
                break
        return [
            {"name": d["place_name"],
             "lat":  float(d["y"]),
             "lon":  float(d["x"]),
             "distance": int(d.get("distance", 0))}
            for d in all_docs
        ]
    except Exception as e:
        log.warning(f"카카오 API 오류 ({category}): {e}")
        return []


def get_area_stations(center_lat: float, center_lon: float,
                      radius: int = 4000) -> list:
    """
    지역 내 지하철역 목록 반환 (세션 캐시).
    카카오 API 있으면 동적 조회, 없으면 폴백 데이터 사용.
    """
    cache_key = (round(center_lat, 2), round(center_lon, 2))
    if cache_key in _kakao_station_cache:
        return _kakao_station_cache[cache_key]

    stations = _kakao_category(center_lat, center_lon, "SW8", radius)
    if stations:
        log.info(f"카카오 API: {len(stations)}개 지하철역 조회됨")
        _kakao_station_cache[cache_key] = stations
        return stations

    # 폴백: 하드코딩 데이터
    log.info("카카오 API 키 없음 → 폴백 역 데이터 사용")
    _kakao_station_cache[cache_key] = _FALLBACK_STATIONS
    return _FALLBACK_STATIONS


def get_area_bus_stops(center_lat: float, center_lon: float,
                       radius: int = 500) -> list:
    """
    주변 버스정류장 조회 (카카오 키워드 검색).
    카카오 로컬 API에는 버스정류장 카테고리가 없으므로 키워드 검색 사용.
    """
    key = _kakao_key()
    if not key:
        return []
    try:
        import requests
        r = requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": "버스정류장",
                    "x": center_lon, "y": center_lat,
                    "radius": radius, "sort": "distance", "size": 15},
            headers={"Authorization": f"KakaoAK {key}"},
            timeout=6,
        )
        return [
            {"name": d["place_name"],
             "lat":  float(d["y"]),
             "lon":  float(d["x"]),
             "distance": int(d.get("distance", 0))}
            for d in r.json().get("documents", [])
        ]
    except Exception as e:
        log.warning(f"버스정류장 조회 실패: {e}")
        return []


# ════════════════════════════════════════════════════════
#  거리 계산 (Haversine, API 불필요)
# ════════════════════════════════════════════════════════

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 WGS84 좌표 간 직선 거리 (미터)"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_station_name(s: dict) -> tuple[str, str]:
    """역 dict에서 (역명, 호선) 추출.
    Kakao API는 '화곡역 5호선' 형식으로 반환; 폴백 데이터는 'line' 키 별도 보유.
    """
    line = s.get("line", "")
    raw = s["name"]  # e.g. "화곡역 5호선" or "화곡"
    if not line:
        # Kakao format: "화곡역 5호선" → name="화곡", line="5호선"
        clean = raw.replace("역", "", 1)  # 첫 번째 '역'만 제거
        parts = clean.split(" ", 1)
        if len(parts) == 2 and ("호선" in parts[1] or "선" in parts[1]):
            return parts[0].strip(), parts[1].strip()
        return clean.strip(), ""
    return raw.replace("역", "").strip(), line


def nearest_subway(lat: float, lon: float,
                   stations: list | None = None) -> dict:
    """
    가장 가까운 지하철역 반환.
    stations: get_area_stations()로 미리 받은 목록 (없으면 폴백 사용)
    """
    if not lat or not lon:
        return {}
    pool = stations if stations else _FALLBACK_STATIONS
    if not pool:
        return {}
    best = min(pool, key=lambda s: haversine(lat, lon, s["lat"], s["lon"]))
    dist = round(haversine(lat, lon, best["lat"], best["lon"]))
    walk_min = max(1, round(dist / 67))  # 보행속도 4km/h = 67m/분
    name, line = _parse_station_name(best)
    return {"station": name, "line": line, "dist_m": dist, "walk_min": walk_min}


def top_subways(lat: float, lon: float, top_n: int = 3,
                stations: list | None = None) -> list:
    """가까운 지하철역 상위 N개"""
    if not lat or not lon:
        return []
    pool = stations if stations else _FALLBACK_STATIONS
    ranked = sorted(pool, key=lambda s: haversine(lat, lon, s["lat"], s["lon"]))
    result = []
    for s in ranked[:top_n]:
        dist = round(haversine(lat, lon, s["lat"], s["lon"]))
        name, line = _parse_station_name(s)
        result.append({
            "station": name,
            "line": line,
            "dist_m": dist,
            "walk_min": max(1, round(dist / 67)),
        })
    return result


# ════════════════════════════════════════════════════════
#  고도 / 경사도 (OpenTopoData 무료 API)
# ════════════════════════════════════════════════════════

def get_elevation(lat: float, lon: float) -> float | None:
    """OpenTopoData SRTM30 고도 (미터). 응답 1~3초."""
    try:
        import requests
        r = requests.get(
            f"https://api.opentopodata.org/v1/srtm30m?locations={lat:.6f},{lon:.6f}",
            timeout=6,
        )
        return r.json()["results"][0]["elevation"]
    except Exception as e:
        log.warning(f"고도 조회 실패: {e}")
        return None


def estimate_slope(lat: float, lon: float, delta: float = 0.0005) -> float | None:
    """
    인근 4방향 고도로 최대 경사도 추정 (%).
    delta=0.0005 ≈ 북/남 55m, 동/서 44m.
    5지점 1회 API 호출.

    기준: <5% 평지 / 5~10% 완만 / 10~15% 가파름 / >15% 매우 가파름
    """
    try:
        import requests
        pts = [
            (lat + delta, lon), (lat - delta, lon),
            (lat, lon + delta), (lat, lon - delta),
            (lat, lon),
        ]
        locs = "|".join(f"{la:.6f},{lo:.6f}" for la, lo in pts)
        r = requests.get(
            f"https://api.opentopodata.org/v1/srtm30m?locations={locs}",
            timeout=10,
        )
        elevs = [res["elevation"] for res in r.json()["results"]]
        base  = elevs[4]
        if base is None:
            return None
        horiz = haversine(lat, lon, lat + delta, lon)
        slopes = [abs(e - base) / horiz * 100 for e in elevs[:4] if e is not None]
        return round(max(slopes), 1) if slopes else None
    except Exception as e:
        log.warning(f"경사도 추정 실패: {e}")
        return None


def slope_label(slope_pct: float | None) -> str:
    """경사도 → 접근성 평가 텍스트"""
    if slope_pct is None:
        return "데이터없음"
    if slope_pct >= 15:
        return "⚠️ 매우 가파름 (도보 불편)"
    if slope_pct >= 10:
        return "🟡 가파름 (경사로 있음)"
    if slope_pct >= 5:
        return "🟢 보통 (완만한 경사)"
    return "✅ 평지 (접근 양호)"


# ── 하위 호환성 (기존 코드가 SUBWAY_STATIONS 직접 참조 시) ──────────
SUBWAY_STATIONS = _FALLBACK_STATIONS
