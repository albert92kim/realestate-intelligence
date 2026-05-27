@echo off
:: 수집 후 GitHub push → Streamlit Cloud 자동 갱신
:: 이 파일을 수집 완료 후 실행하거나, 수집 스케줄러에 연결

cd /d "C:\Users\Albert\AI스크래핑\realestate"

echo [%date% %time%] SQLite → GitHub 동기화 시작...

git add data\realestate.db
git commit -m "Data update %date% %time%"
git push origin main

echo [%date% %time%] 완료! Streamlit Cloud 1-2분 내 자동 갱신됩니다.
pause
