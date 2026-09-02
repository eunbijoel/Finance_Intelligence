

# Finance Intelligence

국내 기업 공시·재무정보와 사업계획서를 통합 분석하여 **심사역 검토 보조용** 메모 초안을 생성하는 AI 금융 리서치 워크벤치 MVP입니다.

> ⚠️ 본 도구는 대출 승인/거절, 신용등급, 한도 산정, 투자 추천 시스템이 **아닙니다**.

## 실행 방법

```bash
cd finance_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 필요 시 API 키 입력
streamlit run app.py
```

DART API 키가 없어도 **삼성전자(005930) 샘플 데이터**로 실행 가능합니다.

## 화면

1. **기업 대시보드** — DART/mock 재무정보, Python 재무비율, Plotly 추이
2. **기업자료 검토** — PDF/DOCX/XLSX/CSV/TXT 업로드 및 근거 추출
3. **Credit Review Workspace** — Agent 워크플로우, 위험 신호, 검토 메모

## 테스트

```bash
pytest tests/ -v
```





## OpenDART 연결

`.env`에 `DART_API_KEY`를 설정하면 live DART API를 사용합니다.  
[OpenDART](https://opendart.fss.or.kr/)에서 API 키를 발급받으세요.

## LLM (선택)

`.env`에 `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`을 설정하거나  
`FI_MOCK_LLM=true`로 mock 응답을 사용할 수 있습니다.

## 위험 규칙 임계값

`config.py`의 `RISK_THRESHOLDS`에서 수정합니다.