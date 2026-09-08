# Finance Intelligence

[한국어 README](README.md)

A tool that reviews **Korean company disclosures and financials (OpenDART)** together with **uploaded documents such as business plans**, then drafts **reviewer memos, follow-up questions, and risk signals**.

> **Important**  
> This software does **not** automatically approve or reject loans.  
> It does **not** assign credit ratings, set limits, or recommend investments.  
> On-screen **Review approval** is **not** a loan approval — it means the **Checker finished reviewing the materials and memo**.

---

## In one sentence

A prototype where you **create a review case → Maker analyzes and writes comments → Checker reviews and approves**.  
(No real bank login or e-approval — pick a user in the sidebar.)

```
Received → Document review → Maker draft → Checker review → Review approved → Closed
```

---



## Run

Works without an API key using **Samsung Electronics (005930) sample data**.

```bash
cd finance_intelligence
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py --server.port 8506
```

Browser: `http://localhost:8506`

### Example walkthrough

1. Select user **김심사 (MAKER)** in the sidebar
2. **Create new case** → company `삼성전자`, plus Checker, amount, purpose, product, due date
3. Open the case → **Start review**
4. In **Document review**, upload `data/sample_business_plan.txt`
5. In **Agent Workspace**, run AI integrated review → write Maker comments → save → request Checker review
6. Switch to **박책임 (CHECKER)** → in **Checker review**, confirm and **Review approve**
7. In **Analysis & audit history**, check who did what

For live OpenDART data, set `DART_API_KEY` under [Configuration](#configuration-env).  
You can still search a company in the sidebar **without** a case (legacy flow).

---



## Who does what?


| Role        | Can do                                                                  | Cannot do                     |
| ----------- | ----------------------------------------------------------------------- | ----------------------------- |
| **Maker**   | Upload docs, run AI analysis, write comments, request Checker review    | Final **review approval**     |
| **Checker** | Compare AI draft vs Maker comments, request changes, **review approve** | (Only cases assigned to them) |
| **Admin**   | View all / check settings                                               | —                             |


The same person cannot be both Maker and Checker on one case.

---



## Screens



### Left sidebar


| Menu                       | What it does                                        |
| -------------------------- | --------------------------------------------------- |
| **Current user**           | Switch Maker / Checker (demo only — not real login) |
| **Case inbox**             | Your cases (status, due date, risk summary)         |
| **Create new case**        | New case (number like `CR-20260908-0001`)           |
| **Company · Agent review** | Main analysis / review workspace                    |
| **Settings · versions**    | Rule / prompt versions in use                       |
| **Company search**         | Legacy: look up a company without a case            |




### Tabs inside Company · Agent review


| Tab                  | What it does                                           |
| -------------------- | ------------------------------------------------------ |
| **Company review**   | Financial changes, filings, risk signals at a glance   |
| **Document review**  | Upload business plans and extract fields               |
| **Agent Workspace**  | Run AI review, Maker comments, save results            |
| **Checker review**   | Compare original vs edits → request changes or approve |
| **Analysis & audit** | Analysis versions, audit log, reproducibility check    |


---



## Case statuses


| Status              | Meaning                                   |
| ------------------- | ----------------------------------------- |
| Received            | Case created                              |
| In Maker review     | Analyst analyzing / writing comments      |
| Documents requested | More materials needed                     |
| Waiting for Checker | Checker’s turn                            |
| Changes requested   | Checker asked for revisions               |
| Review approved     | **Not a loan approval** — review complete |
| Closed              | Case finished                             |


---



## More detail



### Company review

Shows first: “What should we look at now, and what still needs checking?”

- **What changed** (revenue, profit, cash flow, debt, etc.)
- **Why it matters**, **what to check next**
- Risk cards, financial charts, recent filings


| Overall status       | Meaning                                          |
| -------------------- | ------------------------------------------------ |
| Before analysis      | AI review not run yet                            |
| No material findings | Few rule-based signals → **not an approval**     |
| Needs follow-up      | Questions / more documents needed                |
| Material risk found  | Focused review recommended → **not a rejection** |




### Document review

Upload PDF / DOCX / XLSX / CSV / TXT.  
Extracts fund purpose, revenue outlook, repayment plan, and keeps **evidence location** (page, sheet, etc.) when possible.  
Same filename with different content becomes a new version; identical files are flagged as duplicates.

Sample: `data/sample_business_plan.txt`

### Agent Workspace

Step-by-step analysis of DART financials + documents → memo, cross-checks, risk signals.  
If evidence is weak, it stops instead of forcing a conclusion.  
On save, **AI original text** and **Maker comments** are stored separately.

### Checker review · audit history

- Compare AI draft / Maker edits / differences  
- Three confirmation checkboxes required before approval (not automated financial judgment, etc.)  
- **Audit log** of who did what when (no edit/delete)  
- **Reproduce** past analysis: compare then vs now documents/versions (LLM wording may differ)

---



## Feature summary

- **Financial ratios:** debt ratio, current ratio, margins, etc. — if missing, shows “not calculable” (no guessing)
- **Risk rules:** e.g. negative operating CF for 2 years, debt surge, plan vs filing mismatch (thresholds in `config.py`)
- **Saved analyses:** versioned in SQLite (not overwritten)
- **LLM:** local Ollama by default; rule-based analysis still works if Ollama is off

---



## Configuration (`.env`)

Create a `.env` file in the project root yourself. Do not commit it.


| Variable                       | Description                                          |
| ------------------------------ | ---------------------------------------------------- |
| `DART_API_KEY`                 | [OpenDART](https://opendart.fss.or.kr/) API key      |
| `LLM_PROVIDER`                 | `ollama` (default) or `openai`                       |
| `OLLAMA_BASE_URL`              | Ollama URL                                           |
| `LLM_MODEL`                    | Model name (default `gemma4:31b`)                    |
| `LLM_BASE_URL` / `LLM_API_KEY` | When using openai                                    |
| `FI_MOCK_LLM`                  | `true` skips LLM calls                               |
| `FI_DB_PATH`                   | SQLite path (default `data/finance_intelligence.db`) |


---



## Project layout

```
finance_intelligence/
├── app.py                 # UI (inbox / review tabs)
├── case_management.py     # Cases, status, comments
├── audit_service.py       # Audit log (append-only)
├── document_registry.py   # File hash / upload registry
├── versioning.py          # Version / role / status constants
├── reproduction.py        # Reproducibility checks
├── dart_client.py         # OpenDART / sample data
├── document_parser.py     # Document parsing
├── financial_analysis.py  # Ratios, risks, cross-checks
├── agent_workflow.py      # AI integrated review steps
├── database.py            # SQLite
├── config.py              # Settings / thresholds
├── ui_helpers.py          # UI copy / reports
├── data/                  # DB, uploads/, sample docs
├── tests/
└── requirements.txt
```

---



## Good to know

- No real SSO login, e-approval, or bank network integration (demo user picker only)
- Filing **body PDFs are not deeply parsed** (list + links oriented)
- Final financial judgment always stays with a **human**
- Reproduction checks “same conditions,” not 100% identical AI wording



## TODO

- Excel / DOCX review report export  
- Deeper filing body / footnote linkage  
- Real auth / approval integration

Questions or ideas? Open an issue or PR.