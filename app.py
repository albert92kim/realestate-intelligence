# -*- coding: utf-8 -*-
"""
네이버 부동산 인텔리전스 대시보드
실행: streamlit run app.py
"""
import sys, os, json
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent))

# ── 클라우드/로컬 통합 Secrets 브리지 ─────────────────
# Streamlit Cloud: st.secrets → os.environ 으로 내보내기
# 로컬: config.py 가 .env 를 읽음 (이미 처리됨)
try:
    import streamlit as _st
    for _k, _v in _st.secrets.items():
        os.environ.setdefault(str(_k), str(_v))
except Exception:
    pass

# ── Playwright 가용성 확인 (클라우드에서는 비활성화) ──
try:
    import playwright  # noqa
    COLLECTION_AVAILABLE = True
except ImportError:
    COLLECTION_AVAILABLE = False

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import (get_conn, init_db, get_watched_nos, get_watchlist_df,
                      add_to_watchlist, remove_from_watchlist, update_watchlist_memo)
from config import SEARCH_CONFIGS, KAKAO_JS_KEY

st.set_page_config(
    page_title="부동산 인텔리전스",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB 초기화 ──────────────────────────────────────────
init_db()


# ── 공통 데이터 로드 ───────────────────────────────────
@st.cache_data(ttl=300)
def load_properties(cortar_no=None, active_only=True):
    with get_conn() as conn:
        q = "SELECT * FROM properties WHERE 1=1"
        params = []
        if active_only:
            q += " AND is_active=1"
        if cortar_no:
            q += " AND cortar_no=?"
            params.append(cortar_no)
        cur = conn.execute(q, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()


@st.cache_data(ttl=300)
def load_market_stats(cortar_no=None, days=30):
    with get_conn() as conn:
        q = """SELECT * FROM market_stats WHERE 1=1"""
        params = []
        if cortar_no:
            q += " AND cortar_no=?"
            params.append(cortar_no)
        q += " ORDER BY stat_date DESC LIMIT ?"
        params.append(days)
        cur = conn.execute(q, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()


@st.cache_data(ttl=300)
def load_runs(limit=20):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM collection_runs ORDER BY run_at DESC LIMIT ?", (limit,)
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()


@st.cache_data(ttl=300)
def load_price_history(article_no):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM price_history WHERE article_no=? ORDER BY changed_at",
            (article_no,)
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()


# ── 카카오 지도 HTML 빌더 ─────────────────────────────
def build_kakao_map(df, kakao_js_key,
                    center_lat, center_lon, avg_price,
                    show_bargain=True, use_cluster=True, show_subway=True,
                    watched_nos=None):
    import json as _json
    if watched_nos is None:
        watched_nos = set()

    props = []
    for _, row in df.iterrows():
        try:
            lat = float(row.get("latitude") or 0)
            lon = float(row.get("longitude") or 0)
        except (TypeError, ValueError):
            continue
        if lat == 0 or lon == 0:
            continue
        price = float(row.get("price_int") or 0)
        if show_bargain and avg_price > 0:
            if price > avg_price * 1.10:
                color, label = "#e74c3c", ""      # 빨강: 고가 (색으로 구분)
            elif price <= avg_price * 0.85:
                color, label = "#27ae60", "급"    # 초록: 급매 표시
            else:
                color, label = "#2980b9", ""      # 파랑: 일반 (색으로 구분)
        else:
            color, label = "#2980b9", ""

        def _s(v): return str(v) if v is not None and str(v) != "nan" else ""
        props.append({
            "lat": lat, "lon": lon,
            "no": _s(row.get("article_no")),
            "price": _s(row.get("price_raw")),
            "area2": _s(row.get("area2")),
            "area1": _s(row.get("area1")),
            "floor": _s(row.get("floor_info")),
            "direction": _s(row.get("direction")),
            "type_name": _s(row.get("type_name")),
            "trade_name": _s(row.get("trade_name")),
            "building": _s(row.get("building_name")),
            "build_year": _s(row.get("build_year")),
            "realtor": _s(row.get("realtor_name")),
            "desc": _s(row.get("description")),
            "article_url": _s(row.get("article_url")),
            "color": color, "label": label,
            "watched": row.get("article_no") in watched_nos,
        })

    props_json = _json.dumps(props, ensure_ascii=False)
    cluster_js = "true" if use_cluster else "false"
    subway_js  = "true" if show_subway else "false"

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_js_key}&libraries=services,clusterer"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Malgun Gothic',sans-serif}}
#map{{width:100%;height:580px}}
#dbg{{position:fixed;top:4px;left:4px;background:rgba(0,0,0,.7);color:#0f0;font-size:11px;padding:4px 8px;border-radius:4px;z-index:9999;font-family:monospace}}
</style>
</head><body>
<div id="dbg">초기화 중...</div>
<div id="map"></div>
<script>
var dbg=document.getElementById('dbg');
window.onerror=function(m,s,l,c,e){{dbg.style.color='#f66';dbg.textContent='ERR: '+m+' ('+s.split('/').pop()+':'+l+')';return false;}};
(function(){{
try{{
dbg.textContent='kakao='+(typeof kakao)+' | loc='+document.location.href.slice(0,40);
var map=new kakao.maps.Map(document.getElementById('map'),{{
  center:new kakao.maps.LatLng({center_lat},{center_lon}),level:5}});
map.addControl(new kakao.maps.ZoomControl(),kakao.maps.ControlPosition.RIGHT);
map.addControl(new kakao.maps.MapTypeControl(),kakao.maps.ControlPosition.TOPRIGHT);

var _open=null;
function closeInfo(){{if(_open){{_open.setMap(null);_open=null;}}}}
kakao.maps.event.addListener(map,'click',closeInfo);

function makeSVG(color,label){{
  var s='<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28">'
    +'<circle cx="14" cy="14" r="12" fill="'+color+'" stroke="white" stroke-width="2"/>'
    +'<text x="14" y="19" text-anchor="middle" fill="white" font-size="11" font-weight="bold" font-family="sans-serif">'+label+'</text>'
    +'</svg>';
  return 'data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(s);
}}
function makeStarSVG(){{
  var s='<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34">'
    +'<polygon points="17,2 21,13 33,13 23,20 27,32 17,25 7,32 11,20 1,13 13,13" '
    +'fill="#FFD700" stroke="white" stroke-width="1.5"/>'
    +'</svg>';
  return 'data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(s);
}}

// ── 매물 마커 ──────────────────────────────────────────
var props={props_json};
var markers=[];
props.forEach(function(p){{
  var pos=new kakao.maps.LatLng(p.lat,p.lon);
  var imgSrc=p.watched?makeStarSVG():makeSVG(p.color,p.label);
  var mSz=p.watched?34:28, mAn=p.watched?17:14;
  var marker=new kakao.maps.Marker({{
    position:pos,
    image:new kakao.maps.MarkerImage(imgSrc,
      new kakao.maps.Size(mSz,mSz),{{offset:new kakao.maps.Point(mAn,mAn)}})
  }});
  // 팝업 래퍼: 정보 패널 + 아래 화살표 + 스페이서(마커 높이만큼)
  var wrap=document.createElement('div');
  wrap.style.cssText='display:inline-block;text-align:center';

  var d=document.createElement('div');
  d.style.cssText='background:white;border:1px solid #ddd;border-radius:8px;padding:10px 14px 10px 12px;font-size:12px;line-height:1.7;box-shadow:0 2px 8px rgba(0,0,0,.15);min-width:220px;max-width:290px;position:relative;text-align:left';
  var nUrl=p.article_url||('https://new.land.naver.com/houses?articleNo='+p.no);
  d.innerHTML=
    (p.watched?'<div style="background:#FFD700;color:#5a4000;border-radius:3px;padding:1px 6px;font-size:10px;margin-bottom:4px;display:inline-block;font-weight:bold">⭐ 관심 매물</div><br>':'')
    +'<span style="position:absolute;top:4px;right:8px;cursor:pointer;font-size:16px;color:#aaa" onclick="(function(e){{e.stopPropagation();if(window._kOpen){{window._kOpen.setMap(null);window._kOpen=null;}}}})()">×</span>'
    +(p.building?'<b style="font-size:13px">'+p.building+'</b><br>':'')
    +'<span style="color:#888;font-size:11px">'+p.type_name+' · '+p.trade_name+'</span><br>'
    +'<span style="color:#e74c3c;font-weight:bold;font-size:15px">'+p.price+'</span>'
    +'<hr style="margin:5px 0;border:none;border-top:1px solid #eee">'
    +'<span style="color:#555;font-size:11px">'
    +(p.area2?'📐 '+p.area2+'m²':'')
    +(p.floor?' &nbsp;🏢 '+p.floor+'층':'')
    +(p.direction?' &nbsp;↗ '+p.direction:'')
    +'</span>'
    +(p.build_year?'<br><span style="color:#777;font-size:11px">🔨 '+p.build_year+'년 건축</span>':'')
    +(p.realtor?'<br><span style="color:#aaa;font-size:10px">🏪 '+p.realtor+'</span>':'')
    +(p.desc?'<br><span style="color:#777;font-size:11px">'+p.desc+'</span>':'')
    +'<hr style="margin:5px 0;border:none;border-top:1px solid #eee">'
    +'<a href="'+nUrl+'" target="_blank" rel="noopener" style="display:inline-block;background:#03c75a;color:white;padding:4px 10px;border-radius:4px;font-size:11px;text-decoration:none;font-weight:bold">🔗 네이버 상세보기</a>'
    +'<br><span style="font-size:10px;color:#bbb">매물 목록 탭의 ★ 체크 → 관심 등록</span>';
  d.onclick=function(e){{e.stopPropagation();}};

  // 아래 방향 화살표 (팝업 → 마커 연결)
  var arrow=document.createElement('div');
  arrow.style.cssText='width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;border-top:8px solid #ddd;margin:0 auto';
  var arrowInner=document.createElement('div');
  arrowInner.style.cssText='width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-top:7px solid white;margin:-9px auto 0';

  // 스페이서: 마커 중심에서 하단까지 (14px) + 여백 2px
  var spacer=document.createElement('div');
  spacer.style.height='16px';

  wrap.appendChild(d);
  wrap.appendChild(arrow);
  wrap.appendChild(arrowInner);
  wrap.appendChild(spacer);

  var ov=new kakao.maps.CustomOverlay({{content:wrap,position:pos,yAnchor:1.0,zIndex:10}});
  kakao.maps.event.addListener(marker,'click',function(){{
    if(window._kOpen===ov){{closeInfo();}}
    else{{closeInfo();ov.setMap(map);window._kOpen=_open=ov;}}
  }});
  markers.push(marker);
}});

if({cluster_js}){{
  new kakao.maps.MarkerClusterer({{
    map:map,markers:markers,averageCenter:true,minLevel:6,
    styles:[{{width:'40px',height:'40px',background:'rgba(41,128,185,.85)',
              borderRadius:'20px',color:'white',textAlign:'center',
              lineHeight:'40px',fontWeight:'bold',fontSize:'13px'}}]
  }});
}}else{{
  markers.forEach(function(m){{m.setMap(map);}});
}}

// ── 지하철역 마커 (Kakao Maps JS SDK 직접 검색 — 타일과 동일 DB) ──
// REST API 좌표 사용 금지: REST API DB와 지도 타일 DB의 좌표가 다를 수 있음
if({subway_js}){{
  var ps=new kakao.maps.services.Places();
  function parseName(n){{
    // "화곡역 5호선" → {{name:"화곡", line:"5호선"}}
    var c=n.replace(/역/,'');
    var sp=c.indexOf(' ');
    return sp>0?{{name:c.slice(0,sp),line:c.slice(sp+1)}}:{{name:c,line:''}};
  }}
  function addStnMarkers(data,status,pagination){{
    if(status!==kakao.maps.services.Status.OK)return;
    data.forEach(function(pl){{
      var pos=new kakao.maps.LatLng(pl.y,pl.x);
      var nm=parseName(pl.place_name);
      var sd=document.createElement('div');
      sd.style.cssText='background:#8e44ad;color:white;border:2px solid #6c3483;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,.3)';
      sd.innerHTML='🚇';sd.title=nm.name+'역('+nm.line+')';
      var id2=document.createElement('div');
      id2.style.cssText='background:white;border:1px solid #ddd;border-radius:8px;padding:8px 12px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.15);white-space:nowrap';
      id2.innerHTML='<b>🚇 '+nm.name+'역</b><br>'+nm.line;
      id2.onclick=function(e){{e.stopPropagation();}};
      var ov2=new kakao.maps.CustomOverlay({{content:id2,position:pos,yAnchor:2.35,zIndex:10}});
      sd.onclick=function(e){{
        e.stopPropagation();
        if(window._kOpen===ov2){{closeInfo();}}
        else{{closeInfo();ov2.setMap(map);window._kOpen=_open=ov2;}}
      }};
      new kakao.maps.CustomOverlay({{map:map,content:sd,position:pos,yAnchor:0.5,zIndex:5}});
    }});
    if(!pagination.isEnd)pagination.nextPage();
  }}
  ps.categorySearch('SW8',addStnMarkers,{{
    location:new kakao.maps.LatLng({center_lat},{center_lon}),
    radius:4000,
    sort:kakao.maps.services.SortBy.DISTANCE
  }});
}}
dbg.textContent='지도 렌더링 완료 ✓';
}}catch(e){{dbg.style.color='#f66';dbg.textContent='CATCH: '+e.message;}}
}})();
</script>
</body></html>"""
    return html


# ── 사이드바 ───────────────────────────────────────────
st.sidebar.title("🏠 부동산 인텔리전스")

cortar_options = {c["cortar_address"]: c["cortar_no"] for c in SEARCH_CONFIGS}
selected_addr = st.sidebar.selectbox("지역 선택", list(cortar_options.keys()))
selected_cortar = cortar_options[selected_addr]

st.sidebar.divider()
if COLLECTION_AVAILABLE:
    if st.sidebar.button("🔄 수동 수집 실행", use_container_width=True):
        with st.spinner("수집 중..."):
            from collector import run_collection
            total, new, updated, deleted = run_collection()
            st.sidebar.success(f"완료! 총:{total} 신규:{new} 변경:{updated}")
            st.cache_data.clear()
else:
    st.sidebar.info("☁️ 클라우드 환경\n수집은 로컬 PC에서 실행 후\nGitHub에 push하면 자동 반영됩니다.")

# ── 탭 ────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["📊 대시보드", "📋 매물 목록", "🗺️ 지도", "⭐ 관심 매물", "🤖 AI 분석", "⚙️ 설정"]
)

# ══════════════════════════════════════════════════════
# TAB 1: 대시보드
# ══════════════════════════════════════════════════════
with tab1:
    st.header(f"📊 {selected_addr} 시장 현황")

    df = load_properties(selected_cortar)

    if df.empty:
        st.info("수집된 데이터가 없습니다. 사이드바에서 '수동 수집 실행'을 눌러주세요.")
    else:
        # KPI 카드
        col1, col2, col3, col4 = st.columns(4)
        total_cnt = len(df)
        avg_price = int(df["price_int"].mean()) if total_cnt else 0
        median_price = int(df["price_int"].median()) if total_cnt else 0

        # 오늘 신규
        today = date.today().strftime("%Y-%m-%d")
        new_today = len(df[df["first_seen"].str.startswith(today)]) if "first_seen" in df.columns else 0

        # 급매 (평균 대비 15% 이하)
        bargain_threshold = avg_price * 0.85
        bargain_cnt = len(df[df["price_int"] <= bargain_threshold]) if avg_price else 0

        col1.metric("총 매물", f"{total_cnt:,}건")
        col2.metric("평균가", f"{avg_price:,}만원")
        col3.metric("오늘 신규", f"+{new_today}건")
        col4.metric("급매 후보", f"{bargain_cnt}건 ⚠️" if bargain_cnt else "0건")

        st.divider()

        # 가격 추이 차트
        df_stats = load_market_stats(selected_cortar, 30)
        if not df_stats.empty:
            df_stats = df_stats.sort_values("stat_date")
            fig = px.line(
                df_stats, x="stat_date", y="avg_price",
                title="30일 평균가 추이 (만원)",
                labels={"stat_date": "날짜", "avg_price": "평균가(만원)"},
                markers=True,
            )
            fig.update_layout(height=300)
            st.plotly_chart(fig, width='stretch')

        col_l, col_r = st.columns(2)

        with col_l:
            # 가격대별 분포
            fig2 = px.histogram(
                df[df["price_int"] > 0], x="price_int", nbins=20,
                title="가격대별 분포 (만원)",
                labels={"price_int": "가격(만원)"},
                color_discrete_sequence=["#3B82F6"],
            )
            fig2.update_layout(height=280)
            st.plotly_chart(fig2, width='stretch')

        with col_r:
            # 물건 유형별 파이
            if "type_name" in df.columns:
                fig3 = px.pie(
                    df, names="type_name", title="물건 유형별 비율",
                    hole=0.4,
                )
                fig3.update_layout(height=280)
                st.plotly_chart(fig3, width='stretch')


# ══════════════════════════════════════════════════════
# TAB 2: 매물 목록
# ══════════════════════════════════════════════════════
with tab2:
    st.header("📋 매물 목록")

    df_all = load_properties(selected_cortar)
    if df_all.empty:
        st.info("데이터 없음")
    else:
        # 필터
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            types = ["전체"] + sorted(df_all["type_name"].dropna().unique().tolist())
            sel_type = st.selectbox("물건 유형", types)
        with col2:
            min_p = int(df_all["price_int"].min()) if len(df_all) else 0
            max_p = int(df_all["price_int"].max()) if len(df_all) else 100000
            price_range = st.slider("가격 범위 (만원)", min_p, max_p, (min_p, max_p), step=500)
        with col3:
            sort_opts = {"가격 낮은순": "price_int", "가격 높은순": "-price_int",
                         "최신순": "-first_seen", "면적 큰순": "-area2"}
            sel_sort = st.selectbox("정렬", list(sort_opts.keys()))
        with col4:
            show_bargain = st.checkbox("급매만 보기")

        df_f = df_all.copy()
        if sel_type != "전체":
            df_f = df_f[df_f["type_name"] == sel_type]
        df_f = df_f[(df_f["price_int"] >= price_range[0]) & (df_f["price_int"] <= price_range[1])]
        if show_bargain:
            avg = df_all["price_int"].mean()
            df_f = df_f[df_f["price_int"] <= avg * 0.85]

        sort_col = sort_opts[sel_sort].lstrip("-")
        ascending = not sort_opts[sel_sort].startswith("-")
        df_f = df_f.sort_values(sort_col, ascending=ascending)

        st.caption(f"필터 결과: {len(df_f)}건 &nbsp;|&nbsp; ★ 열 체크 → 관심 매물 등록")

        # 관심 매물 상태 로드 (캐시 없이 항상 최신)
        watched_nos_t2 = get_watched_nos()

        # 지하철 거리 계산 (카카오 API 우선 → 폴백 하드코딩)
        try:
            from enricher import nearest_subway, get_area_stations
            center_lat2 = df_f["latitude"][df_f["latitude"] != 0].mean()
            center_lon2 = df_f["longitude"][df_f["longitude"] != 0].mean()
            _area_stns = get_area_stations(center_lat2, center_lon2)

            def subway_label(row):
                lat, lon = row.get("latitude"), row.get("longitude")
                if not lat or not lon or lat == 0:
                    return ""
                info = nearest_subway(float(lat), float(lon), _area_stns)
                if not info:
                    return ""
                line = f"({info['line']})" if info.get("line") else ""
                return f"{info['station']}역{line} {info['dist_m']:,}m/{info['walk_min']}분"

            df_f = df_f.copy()
            df_f["subway_info"] = df_f.apply(subway_label, axis=1)
            has_subway = True
        except Exception:
            has_subway = False

        # 표시 컬럼
        show_cols = ["type_name", "trade_name", "price_raw", "area1", "area2",
                     "floor_info", "direction", "build_year", "description",
                     "first_seen", "article_url"]
        if has_subway:
            show_cols.insert(show_cols.index("first_seen"), "subway_info")
        show_cols = [c for c in show_cols if c in df_f.columns]

        rename_map = {
            "type_name": "유형", "trade_name": "거래",
            "price_raw": "가격", "area1": "공급m²", "area2": "전용m²",
            "floor_info": "층", "direction": "방향", "build_year": "건축",
            "description": "설명", "subway_info": "지하철거리",
            "first_seen": "수집일", "article_url": "매물링크",
        }

        # ★ 관심 열 + article_no 추가 (data_editor용)
        df_edit = df_f.copy()
        df_edit.insert(0, "★", df_edit["article_no"].isin(watched_nos_t2) if "article_no" in df_edit.columns else False)
        edit_cols = ["★"] + show_cols + (["article_no"] if "article_no" in df_edit.columns else [])
        edit_cols = [c for c in dict.fromkeys(edit_cols) if c in df_edit.columns]

        col_cfg_t2 = {
            "★": st.column_config.CheckboxColumn("★", help="체크 → 관심 매물 등록/해제", width="small"),
            "article_no": st.column_config.TextColumn("매물ID", width="small"),
            "article_url": st.column_config.LinkColumn("매물링크", display_text="🔗 보기"),
        }
        col_cfg_t2.update({k: st.column_config.TextColumn(v) for k, v in rename_map.items() if k in edit_cols})
        disable_t2 = [c for c in edit_cols if c != "★"]

        edited_t2 = st.data_editor(
            df_edit[edit_cols],
            column_config=col_cfg_t2,
            disabled=disable_t2,
            hide_index=True,
            use_container_width=True,
            height=450,
            num_rows="fixed",
        )

        # 관심 매물 변경 감지 및 저장
        if "article_no" in edited_t2.columns:
            _changed = False
            for _, _row in edited_t2.iterrows():
                _no = str(_row.get("article_no", ""))
                if not _no:
                    continue
                _now_w = bool(_row.get("★", False))
                _was_w = _no in watched_nos_t2
                if _now_w and not _was_w:
                    add_to_watchlist(_no)
                    _changed = True
                elif not _now_w and _was_w:
                    remove_from_watchlist(_no)
                    _changed = True
            if _changed:
                st.toast("관심 매물 목록이 업데이트됐습니다. ⭐")
                st.rerun()

        # 엑셀 다운로드
        from io import BytesIO
        buf = BytesIO()
        df_f.to_excel(buf, index=False)
        st.download_button(
            "📥 엑셀 다운로드",
            buf.getvalue(),
            file_name=f"매물_{selected_addr}_{date.today()}.xlsx",
            mime="application/vnd.ms-excel",
        )

        # 경사도·고도 분석 (OpenTopoData API, 선택 매물만)
        st.divider()
        with st.expander("🏔️ 경사도·고도 분석 (선택 매물)"):
            st.caption(
                "OpenTopoData 무료 API로 고도·최대경사도 조회 — 매물당 약 2~3초 소요. "
                "경사도 15%↑는 도보 접근 불편."
            )
            df_geo = df_f[(df_f["latitude"].notna()) & (df_f["latitude"] != 0)].copy()
            if df_geo.empty:
                st.info("좌표 데이터 없음")
            else:
                article_labels = {
                    row["article_no"]: (
                        f"#{str(row['article_no'])[-5:]} | "
                        f"{row.get('price_raw', '')} | "
                        f"{row.get('floor_info', '')} | "
                        f"{row.get('type_name', '')}"
                    )
                    for _, row in df_geo.iterrows()
                    if "article_no" in df_geo.columns
                }
                if article_labels:
                    sel_nos = st.multiselect(
                        "분석할 매물 선택 (최대 5건)",
                        list(article_labels.keys()),
                        format_func=lambda x: article_labels[x],
                        max_selections=5,
                    )
                    if sel_nos and st.button("📡 고도·경사도 분석 실행"):
                        from enricher import get_elevation, estimate_slope, slope_label
                        results = []
                        for no in sel_nos:
                            row = df_geo[df_geo["article_no"] == no].iloc[0]
                            lat, lon = float(row["latitude"]), float(row["longitude"])
                            with st.spinner(f"분석 중: {article_labels[no][:25]}..."):
                                elev  = get_elevation(lat, lon)
                                slope = estimate_slope(lat, lon)
                            results.append({
                                "매물":        article_labels[no][:35],
                                "고도(m)":     elev,
                                "최대경사도(%)": slope,
                                "접근성평가":  slope_label(slope),
                            })
                        st.dataframe(pd.DataFrame(results), width='stretch')


# ══════════════════════════════════════════════════════
# TAB 3: 지도 (Kakao Maps JavaScript API)
# ══════════════════════════════════════════════════════
with tab3:
    st.header("🗺️ 매물 위치 지도")

    df_map = load_properties(selected_cortar)
    df_map = df_map[(df_map["latitude"].notna()) & (df_map["longitude"].notna())]
    df_map = df_map[(df_map["latitude"] != 0) & (df_map["longitude"] != 0)]

    if df_map.empty:
        st.info("좌표 데이터 없음")
    else:
        col_opt1, col_opt2, col_opt3 = st.columns(3)
        with col_opt1:
            show_bargain_map = st.checkbox("급매 강조 표시", value=True)
        with col_opt2:
            use_cluster = st.checkbox("클러스터링", value=True)
        with col_opt3:
            show_subway_map = st.checkbox("🚇 지하철역 표시", value=True)

        avg_price_map = float(df_map["price_int"].mean())
        center_lat = float(df_map["latitude"].mean())
        center_lon = float(df_map["longitude"].mean())

        kakao_js_key = KAKAO_JS_KEY or os.environ.get("KAKAO_JS_KEY", "")

        if not kakao_js_key:
            st.warning("KAKAO_JS_KEY가 .env에 없습니다. ⚙️ 설정 탭을 확인하세요.")
        else:
            map_html = build_kakao_map(
                df_map, kakao_js_key,
                center_lat, center_lon, avg_price_map,
                show_bargain=show_bargain_map,
                use_cluster=use_cluster,
                show_subway=show_subway_map,
                watched_nos=get_watched_nos(),
            )
            st.components.v1.html(map_html, height=590, scrolling=False)

        st.markdown(
            "**마커:** ⭐ 관심 매물(금별) &nbsp; 🟢 **급**매(평균-15% 이하) &nbsp; 🔵 일반 매물 &nbsp; 🔴 고가(평균+10% 이상) &nbsp; 🟣 지하철역"
            "  \n*마커 클릭 → 상세 팝업 + 네이버 링크 | 관심 등록은 매물 목록 탭의 ★ 체크*"
        )


# ══════════════════════════════════════════════════════
# TAB 4: 관심 매물
# ══════════════════════════════════════════════════════
with tab4:
    st.header("⭐ 관심 매물 추적")

    wdf = get_watchlist_df()

    if wdf.empty:
        st.info("등록된 관심 매물이 없습니다. **매물 목록** 탭에서 ★ 열을 체크하면 여기에 추가됩니다.")
    else:
        active_w = int(wdf["is_active"].sum()) if "is_active" in wdf.columns else len(wdf)
        inactive_w = len(wdf) - active_w

        col_w1, col_w2, col_w3 = st.columns(3)
        col_w1.metric("추적 중인 매물", f"{len(wdf)}건")
        col_w2.metric("현재 매물 중", f"{active_w}건")
        col_w3.metric("거래완료 추정", f"{inactive_w}건 🔴" if inactive_w else "0건")

        st.divider()

        for _, wrow in wdf.iterrows():
            no = str(wrow.get("article_no", ""))
            price = str(wrow.get("price_raw", "") or "")
            type_n = str(wrow.get("type_name", "") or "")
            trade_n = str(wrow.get("trade_name", "") or "")
            building = str(wrow.get("building_name", "") or "")
            is_active = bool(wrow.get("is_active", 1))
            status = "🟢 매물 중" if is_active else "🔴 거래완료 추정"

            title = f"{building or type_n} | {price} | {trade_n} | {status}"
            with st.expander(f"⭐ {title}", expanded=False):
                col_l, col_r = st.columns([1, 1])

                with col_l:
                    if building:
                        st.markdown(f"**{building}**")
                    st.markdown(f"**가격:** <span style='color:#e74c3c;font-size:16px'>{price}</span>", unsafe_allow_html=True)

                    details = []
                    area2 = wrow.get("area2")
                    floor = str(wrow.get("floor_info", "") or "")
                    direction = str(wrow.get("direction", "") or "")
                    build_year = wrow.get("build_year")
                    if area2: details.append(f"📐 전용 {area2}m²")
                    if floor: details.append(f"🏢 {floor}층")
                    if direction: details.append(f"↗ {direction}")
                    if build_year: details.append(f"🔨 {build_year}년")
                    if details:
                        st.caption(" &nbsp; ".join(details))

                    desc = str(wrow.get("description", "") or "")
                    realtor = str(wrow.get("realtor_name", "") or "")
                    added_at = str(wrow.get("added_at", ""))[:10]
                    if desc:
                        st.caption(desc)
                    if realtor:
                        st.caption(f"🏪 {realtor}")
                    st.caption(f"관심 등록일: {added_at}")

                    art_url = str(wrow.get("article_url", "") or "")
                    naver_url = art_url if art_url else f"https://new.land.naver.com/houses?articleNo={no}"
                    st.markdown(f"[🔗 네이버 상세보기]({naver_url})")

                    st.divider()
                    cur_memo = str(wrow.get("memo", "") or "")
                    new_memo = st.text_area(
                        "📝 메모", cur_memo, height=100, key=f"memo_{no}",
                        placeholder="투자 검토 의견, 방문 일자, 협의 내용 등..."
                    )
                    col_s, col_d = st.columns(2)
                    with col_s:
                        if st.button("💾 메모 저장", key=f"save_{no}", use_container_width=True):
                            update_watchlist_memo(no, new_memo)
                            st.toast("메모 저장됨 ✓")
                    with col_d:
                        if st.button("🗑️ 관심 해제", key=f"rm_{no}", type="secondary", use_container_width=True):
                            remove_from_watchlist(no)
                            st.rerun()

                with col_r:
                    hist = load_price_history(no)
                    if not hist.empty and "price_int" in hist.columns:
                        hist_plot = hist[hist["price_int"] > 0].copy()
                    else:
                        hist_plot = pd.DataFrame()

                    if hist_plot.empty:
                        st.info("가격 이력 없음\n(수집 시작 이후 변동 없음)")
                    else:
                        type_labels = {"NEW": "신규", "UP": "↑상승", "DOWN": "↓하락", "DELETED": "삭제"}
                        hist_plot["변동"] = hist_plot["change_type"].map(lambda x: type_labels.get(x, x))
                        hist_plot["날짜"] = hist_plot["changed_at"].str[:10]

                        fig_h = px.line(
                            hist_plot, x="날짜", y="price_int",
                            markers=True,
                            title="가격 변동 이력",
                            labels={"price_int": "가격(만원)", "날짜": ""},
                            color_discrete_sequence=["#e74c3c"],
                        )
                        fig_h.update_layout(height=220, margin=dict(t=30, b=10, l=10, r=10))
                        st.plotly_chart(fig_h, use_container_width=True)

                        hist_tbl = hist_plot[["날짜", "price_raw", "변동", "change_amount"]].rename(
                            columns={"price_raw": "가격", "change_amount": "변동액(만원)"}
                        )
                        st.dataframe(hist_tbl, use_container_width=True, height=130, hide_index=True)


# ══════════════════════════════════════════════════════
# TAB 5: AI 분석
# ══════════════════════════════════════════════════════
with tab5:
    st.header("🤖 Gemini AI 분석")

    analysis_type = st.radio(
        "분석 유형",
        ["급매 감지", "시장 동향", "키워드 분석"],
        horizontal=True,
    )

    if st.button("🚀 분석 실행", type="primary"):
        from analyzer import detect_bargains, market_trend_summary, keyword_analysis
        with st.spinner("Gemini 분석 중..."):
            try:
                if analysis_type == "급매 감지":
                    result = detect_bargains(selected_cortar)
                elif analysis_type == "시장 동향":
                    result = market_trend_summary(selected_cortar)
                else:
                    result = keyword_analysis(selected_cortar)

                st.subheader(f"📋 {analysis_type} 결과")
                # JSON이면 예쁘게, 아니면 텍스트로
                try:
                    parsed = json.loads(result)
                    st.json(parsed)
                except Exception:
                    st.markdown(result)

            except Exception as e:
                st.error(f"분석 오류: {e}")


# ══════════════════════════════════════════════════════
# TAB 6: 설정
# ══════════════════════════════════════════════════════
with tab6:
    st.header("⚙️ 설정 및 실행 이력")

    # API 키 상태 패널
    st.subheader("🔑 API 키 상태")
    from enricher import _kakao_key
    kakao_status = _kakao_key()
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        if kakao_status:
            st.success("✅ 카카오 API 키 등록됨 — 지하철/버스 위치 정확")
        else:
            st.warning("⚠️ 카카오 API 키 없음 — 내장 폴백 데이터 사용 중")
            st.markdown("""
**카카오 API 키 발급 방법 (3분, 무료):**
1. [https://developers.kakao.com](https://developers.kakao.com) 접속
2. 카카오 계정으로 로그인 → **내 애플리케이션** 클릭
3. **애플리케이션 추가하기** → 앱 이름 입력 (예: 부동산분석)
4. 생성된 앱의 **REST API 키** 복사
5. `.env` 파일 열기: `C:\\Users\\Albert\\AI스크래핑\\.env`
6. `KAKAO_API_KEY=` 뒤에 복사한 키 붙여넣기 후 저장
7. 대시보드 재시작 → 자동으로 카카오 API 사용

**월 300,000건 무료** (매물 수백 개 기준 충분)
            """)
    with col_k2:
        gemini_count = sum(1 for k in [
            os.environ.get(f"GEMINI_API_KEY{i}" if i else "GEMINI_API_KEY")
            for i in ["", "2", "3", "4", "5", "6"]
        ] if k)
        st.success(f"✅ Gemini API 키 {gemini_count}개 등록됨")

    st.divider()
    st.subheader("수집 조건 목록")
    for cfg in SEARCH_CONFIGS:
        status = "✅ 활성" if cfg.get("active") else "☐ 비활성"
        st.markdown(f"**{status} {cfg['name']}**")
        st.code(cfg["url"], language="text")
        st.divider()

    st.subheader("수집 실행 이력")
    df_runs = load_runs(20)
    if df_runs.empty:
        st.info("실행 이력 없음")
    else:
        show = ["run_at", "total", "new_cnt", "updated_cnt", "deleted_cnt", "status", "duration_sec"]
        show = [c for c in show if c in df_runs.columns]
        st.dataframe(
            df_runs[show].rename(columns={
                "run_at": "실행일시", "total": "수집", "new_cnt": "신규",
                "updated_cnt": "변경", "deleted_cnt": "삭제",
                "status": "상태", "duration_sec": "소요(초)",
            }),
            width='stretch',
        )
