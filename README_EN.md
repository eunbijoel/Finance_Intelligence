# Finance Intelligence

[한국어 README](README.md)

A tool that reviews **Korean company disclosures and financials (OpenDART)** with **uploaded documents such as business plans**, then drafts **reviewer memos, follow-up questions, and risk signals**.

> **Important**  
> This software does **not** automatically approve or reject loans.  
> On-screen **Review complete** is **not** a loan decision — it means the **approver finished checking the materials and memo**.

---

## In one sentence

Create a company review → **register documents → AI review → reviewer confirm → review complete**.  
(No real bank login — pick a user under **Admin info** in the sidebar.)

```
Documents → AI review → Reviewer confirm → Review complete
```

---

## Run

```bash
cd finance_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 8506
```

### Walkthrough

1. Under **Admin info**, select **김심사 (Reviewer)**  
2. **New company review** → enter company, amount, purpose, product, due date, approver → **Start**  
3. **Step 1** upload `data/sample_business_plan.txt` → **Start AI review**  
4. **Step 2** check Critical / Needs check / Missing docs → **Write review opinion**  
5. **Step 3** save opinion → **Send to approver**  
6. Switch to **박책임 (Approver)** → **Step 4** → **Review complete**  
7. Open **Completed reviews**

---

## Sidebar (3 menus)

| Menu | Purpose |
| ---- | ------- |
| **My reviews** | What to do now, due date, step |
| **New company review** | Create and jump to document upload |
| **Completed reviews** | Approved / closed cases |

**Admin info** (collapsed): user switcher, versions, company search without a case.

---

## Roles (UI labels)

| Role | Can | Cannot |
| ---- | --- | ------ |
| **Reviewer** (Maker) | Upload, AI, opinion, send to approver | Final **Review complete** |
| **Approver** (Checker) | Compare, request changes, complete | — |
| **Admin** | View all | — |

Backend role codes (`MAKER` / `CHECKER`) are unchanged.

---

## Feature summary

Ratios, risk rules, cross-checks, document hashing, AI vs human memo separation, analysis versions, audit log, and reproduction remain — technical details are hidden behind expanders.

---

## Configuration (`.env`)

| Variable | Description |
| -------- | ----------- |
| `DART_API_KEY` | OpenDART API key |
| `LLM_PROVIDER` | `ollama` (default) or `openai` |
| `LLM_MODEL` | Default `gemma4:31b` |
| `FI_MOCK_LLM` | `true` skips LLM |
| `FI_DB_PATH` | SQLite path |

Questions or ideas? Open an issue or PR.
