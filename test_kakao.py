# -*- coding: utf-8 -*-
import sys, os
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(r'C:\Users\Albert\AI스크래핑\.env')
import requests

key = os.environ.get('KAKAO_API_KEY', '')
print(f'키 확인: {key[:8]}...')

# 화곡역 근처 지하철역 검색
r = requests.get(
    'https://dapi.kakao.com/v2/local/search/category.json',
    params={
        'category_group_code': 'SW8',  # 지하철역
        'x': 126.850326,
        'y': 37.548787,
        'radius': 4000,
        'sort': 'distance',
        'size': 15,
    },
    headers={'Authorization': f'KakaoAK {key}'},
    timeout=8,
)
data = r.json()
docs = data.get('documents', [])
print(f'\n응답 상태: {r.status_code}')
print(f'지하철역 수: {len(docs)}')
print()
for d in docs:
    print(f"  {d['place_name']:15s}  거리:{d['distance']:>5}m  좌표:({d['y']}, {d['x']})")

# 버스정류장도 테스트
print('\n--- 버스정류장 (반경 500m) ---')
r2 = requests.get(
    'https://dapi.kakao.com/v2/local/search/category.json',
    params={
        'category_group_code': 'BK9',  # 버스정류장 카테고리 확인
        'x': 126.850326,
        'y': 37.548787,
        'radius': 500,
        'sort': 'distance',
        'size': 5,
    },
    headers={'Authorization': f'KakaoAK {key}'},
    timeout=8,
)
data2 = r2.json()
print(f'응답: {r2.status_code}, 결과 수: {len(data2.get("documents", []))}')
for d in data2.get('documents', []):
    print(f"  {d['place_name']:20s}  {d['distance']}m")
