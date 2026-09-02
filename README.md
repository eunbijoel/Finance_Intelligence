# Finance Intelligence

국내 기업 공시·재무정보와 사업계획서를 통합 분석하여 **심사역 검토 보조용** 메모 초안을 생성하는 AI 금융 리서치 워크벤치 MVP입니다.

> 본 도구는 대출 승인/거절, 신용등급, 한도 산정, 투자 추천 시스템이 **아닙니다**.

## 실행 방법

```bash
cd finance_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 프로젝트 루트에 .env 파일을 직접 생성 (Git에 올리지 않음)
streamlit run app.py --server.port 8506
```

DART API 키가 없어도 **삼성전자(005930) 샘플 데이터**로 실행 가능합니다.

## 화면

1. **기업검토 Cockpit** — AI 검토 상태, 재무 변화, 위험 신호, Intelligence 요약
2. **기업자료 검토** — PDF/DOCX/XLSX/CSV/TXT 업로드 및 다중 문서 근거 추출
3. **Agent Workspace** — Agent 워크플로우, 교차검증, 근거 검증, Markdown 보고서

## 테스트

```bash
pytest tests/ -v
```

## 환경 변수

프로젝트 루트에 `.env` 파일을 직접 만드세요 (저장소에 커밋하지 않음).

| 변수 | 설명 |
|------|------|
| `DART_API_KEY` | OpenDART API 키 |
| `LLM_BASE_URL` | LLM API URL (선택) |
| `LLM_API_KEY` | LLM API 키 (선택) |
| `LLM_MODEL` | LLM 모델명 |
| `FI_MOCK_LLM` | `true` 시 mock LLM |
| `FI_DB_PATH` | SQLite DB 경로 (선택) |

## OpenDART 연결

`.env`에 `DART_API_KEY`를 설정하면 live DART API를 사용합니다.  
[OpenDART](https://opendart.fss.or.kr/)에서 API 키를 발급받으세요.

## 위험 규칙 임계값

`config.py`의 `RISK_THRESHOLDS`에서 수정합니다.

## TODO

- Excel/DOCX 보고서 내보내기
