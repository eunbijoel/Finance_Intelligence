# Finance Intelligence

[한국어 README](README.md)

An AI financial research workbench that reviews **Korean company disclosures and financials (OpenDART)** together with **user-uploaded documents such as business plans**, then drafts **reviewer-assist memos, follow-up questions, and risk signals** for credit analysts and researchers.

> **Important:**  
> This is **not** an automatic loan approve/reject system, credit rating engine, limit calculator, or investment recommender.  
> On-screen labels such as “No material findings / Needs follow-up / Material risk found” are **not** approve/reject decisions.

---

## How to use it


| User | Typical use |
| ---- | ----------- |
| Credit / underwriting | Quickly compare disclosed financials with business plans and surface easy-to-miss risks and follow-up questions |
| Corporate finance / research | See recent financial changes, filings, and document inconsistencies in one place |
| Internal review workflow | Save analysis results and reopen or compare prior analyses |


1. Select a company (ticker / company name, with search suggestions)
2. (Optional) Attach a business plan, spreadsheet, or related files
3. Run **AI integrated review**
4. Review risk signals, cross-checks, and the draft memo; edit if needed, then **approve & save**
5. Download a Markdown report, or reopen from **Analysis history** in the sidebar

---

## Example (recommended flow)

Works without an API key using **Samsung Electronics (005930) sample data**.

```bash
cd finance_intelligence
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py --server.port 8506
```

Open `http://localhost:8506` in your browser.

1. In the left **Company search** box, type `삼성` or `005930`
2. Click a **suggested company** button below, or click **Search**
3. On the **Company Review** tab, check financial changes and disclosures
4. (Optional) On **Document Review**, upload `data/sample_business_plan.txt`
5. On **Agent Workspace**, run **AI integrated review** → check risks, memo, and cross-checks
6. If needed, **Approve & save** and **download the Markdown report**

To use live OpenDART companies, set `DART_API_KEY` under [Configuration](#configuration-env) below.

---

## Screen guide

The app is **sidebar** + **three center tabs**.

### Left sidebar


| Area | What it does |
| ---- | ------------ |
| **Company search** | Enter a company name or ticker. While typing, up to **5 suggested companies** appear as buttons. Click one to load that company immediately. |
| **Search** | Find the company from the keyword and load financials and disclosures. |
| **Analysis history** | List of previously **approved & saved** reviews. Click to reopen status, ratios, risks, and memo from that run. Use **Back to current analysis** to leave history view. |


---

### Tab 1 — Company Review

Home screen that prioritizes “What should I look at for this company right now, and what else should I verify?” It summarizes the raw financial tables and puts **changes, meaning, and follow-ups** first.


| Section | Content |
| ------- | ------- |
| **Company header** | Name, ticker, industry, DART code, as-of date, data source (OpenDART / sample) |
| **Shortcut buttons** | Run AI integrated review · Document upload guidance · Review report (Workspace) · Analysis history |
| **Four status cards** | Overall review status · High-risk count · Recent disclosure count · Evidence coverage |
| **What changed** | YoY changes in revenue, operating income, net income, cash flow, debt ratio, etc. (rule-based wording) |
| **Why it matters** | Short interpretation from change/risk rules (no speculation—only confirmed patterns) |
| **What to check** | Reviewer questions and missing materials (up to 5) |
| **Key risk signals** | Risk cards (if none, this means **not detected by current rules**, not “no risk”) |
| **Financial trends** | Plotly chart for revenue, operating income, operating CF |
| **Recent key disclosures** | Title, date, category, DART source link (Korean column labels) |
| **Original financials** | Expand for 억/조-friendly tables and financial ratios |


**Overall review status (meaning)**


| Status | Meaning |
| ------ | ------- |
| Not analyzed yet | AI integrated review has not been run |
| No material findings | Few signals under applied rules and available data → **not an approval** |
| Needs follow-up | Follow-up questions or additional documents needed |
| Material risk found | A high-severity risk rule fired → **not a rejection**; focused review recommended |


---

### Tab 2 — Document Review

Extracts **credit-review fields** from business plans and related materials, and keeps **evidence locations** when possible.

**(Supported formats:** PDF, DOCX, XLSX, CSV, TXT)

**Example extracted fields:**

- Company overview, business purpose, use of proceeds  
- Revenue / cost outlook, repayment plan  
- Major customers, core tech / capabilities, risk factors  
- Items **not found** in the documents  

**Evidence:** file name, page/sheet, cell/location (or “location unknown”), excerpt  
**Multiple files:** if the same field differs across documents, values are **all kept** (not overwritten) → later cross-checks may flag conflicts.

Sample document: `data/sample_business_plan.txt`

---

### Tab 3 — Agent Workspace

**Role:** Combines DART financials + uploaded documents in **steps**, then shows the draft memo, cross-checks, and evidence verification.

**Run:** **AI integrated review** (same workflow as the button on the Company Review tab)

**Agent steps (approximate)**

1. Check inputs → 2. Collect DART data → 3. Analyze documents → 4. Compute ratios  
5. Cross-validate → 6. Detect risks → 7. Verify evidence → 8. Draft memo  
9. User review → 10. Approve & save  

If evidence is insufficient, the agent does not force a conclusion. It stops with `**NEEDS_MORE_INFORMATION**` and shows missing materials and questions.


| Item | Description |
| ---- | ----------- |
| Overall status & summary | Draft memo (richer wording if Ollama is connected; otherwise rule-based summary) |
| Risk signals | Severity (high/medium) + description + evidence figures + review question |
| Cross-checks | Plan revenue vs disclosed figures, doc-to-doc mismatches, use of proceeds / repayment presence, etc. |
| Evidence check | Per claim: supported / partial / unsupported |
| Markdown download | Report file like `CompanyName_review_YYYYMMDD.md` |
| Approve & save | Stored in SQLite → appears in sidebar analysis history |


---



## Feature details

### Financials & ratios (Python)

Revenue, operating income, net income, assets, liabilities, equity, operating CF, plus  
debt ratio, current ratio, operating margin, net margin, ROA, ROE, operating CF / short-term debt, etc.  
If data is missing, the app **does not estimate**—it shows “cannot compute” + reason.

### Risk signals (explicit rules)

Examples: operating CF negative for two years, debt-ratio spike, current-ratio drop, revenue up while profit/CF down,  
short-term debt surge, receivables growth ≫ revenue growth, overly optimistic plan,  
plan vs disclosure mismatch, missing repayment / use of proceeds, etc.

Tune thresholds in `config.py` → `RISK_THRESHOLDS`.

### Cross-validation

Amounts are compared only when numbers and units (e.g. 억 / 조) can be extracted safely.  
If fiscal years differ, the app does **not** call it a hard mismatch—it shows **verify fiscal year**.

### Decision Memory (analysis history)

On approve & save, company, date, documents, ratios, risks, memo, evidence, and user edits go into SQLite.  
Re-analyzing the same company can surface new/resolved risks, worsened/improved ratios, and disclosure/memo difference hints.

### LLM (optional)

Default is local **Ollama** `gemma4:31b`. No API key required.  
If Ollama is down, **rule-based analysis still runs**; only natural-language drafting is weaker.

---

## Configuration (`.env`)

Create a `.env` file in the project root yourself. Do not commit it (listed in `.gitignore`).


| Variable | Description |
| -------- | ----------- |
| `DART_API_KEY` | [OpenDART](https://opendart.fss.or.kr/) API key |
| `LLM_PROVIDER` | `ollama` (default) or `openai` |
| `OLLAMA_BASE_URL` | Ollama base URL |
| `LLM_MODEL` | Model name (default `gemma4:31b`) |
| `LLM_BASE_URL` / `LLM_API_KEY` | Only when `LLM_PROVIDER=openai` |
| `FI_MOCK_LLM` | `true` skips LLM calls |
| `FI_DB_PATH` | SQLite path (default `data/finance_intelligence.db` if empty) |


---

## Project structure

```
finance_intelligence/
├── app.py                 # Streamlit UI (Company Review / Documents / Agent)
├── dart_client.py         # OpenDART + sample data + search/suggestions
├── document_parser.py     # Upload parsing, field extraction, multi-doc merge
├── financial_analysis.py  # Ratios, risk rules, cross-checks, evidence checks
├── agent_workflow.py      # Step agent + LLM (Ollama) adapter
├── database.py            # SQLite Decision Memory
├── config.py              # Env vars, risk thresholds
├── ui_helpers.py          # Display formatting, summaries, Markdown report
├── data/                  # DB, sample_business_plan.txt
├── tests/                 # pytest
├── requirements.txt
├── README.md
└── README_EN.md           # This file
```
---
## MVP limitations

- Deep automatic parsing of full disclosure PDFs is out of scope (list + links focused)
- Excel/DOCX report export is TODO (Markdown is supported)
- The LLM is prompted **not to invent numbers**, but final judgment always stays with the human

## TODO

- Excel / DOCX review report export  
- Deeper linkage to disclosure body text and footnotes  

Questions or ideas? Please open an issue or PR.
