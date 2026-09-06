# Finance Intelligence

An AI financial research workbench MVP that jointly analyzes Korean company disclosures, financials, and business plans to draft **reviewer-assist** memo notes.

> This tool is **not** a loan approve/reject, credit rating, limit-setting, or investment recommendation system.

## How to run

```bash
cd finance_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Create a .env file in the project root (do not commit it to Git)
streamlit run app.py --server.port 8506
```

Even without a DART API key, you can run with **Samsung Electronics (005930) sample data**.

## Screens

1. **Company Review** — AI review status, financial changes, risk signals, summary
2. **Document Review** — Upload PDF/DOCX/XLSX/CSV/TXT and extract evidence across multiple documents
3. **Agent Workspace** — Agent workflow, cross-checks, evidence verification, Markdown report

## Tests

```bash
pytest tests/ -v
```

## Environment variables

Create a `.env` file in the project root (do not commit it to the repository).

| Variable | Description |
|----------|-------------|
| `DART_API_KEY` | OpenDART API key |
| `LLM_PROVIDER` | `ollama` (default) or `openai` |
| `OLLAMA_BASE_URL` | Ollama server URL (default `http://127.0.0.1:11434`) |
| `LLM_MODEL` | Ollama model name (default `gemma4:31b`) |
| `LLM_BASE_URL` | OpenAI-compatible API URL (when `LLM_PROVIDER=openai`) |
| `LLM_API_KEY` | OpenAI-compatible API key (not needed for Ollama) |
| `FI_MOCK_LLM` | If `true`, return mock responses without calling the LLM |
| `FI_DB_PATH` | SQLite DB path (optional) |

## LLM (Ollama — default)

By default the app uses **local Ollama** with **`gemma4:31b`**. No API key is required.

```bash
# Start Ollama and prepare the model (example)
ollama pull gemma4:31b
ollama serve
```

Example `.env` (optional — defaults work without it):

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=gemma4:31b
```

If Ollama is down, only rule-based results are used and LLM narrative text is skipped.  
Force mock mode with: `FI_MOCK_LLM=true`

To use an external OpenAI-compatible API, set `LLM_PROVIDER=openai` plus `LLM_BASE_URL` and `LLM_API_KEY`.

## OpenDART connection

Set `DART_API_KEY` in `.env` to use the live DART API.  
Get an API key from [OpenDART](https://opendart.fss.or.kr/).

## Risk rule thresholds

Edit `RISK_THRESHOLDS` in `config.py`.

## TODO

- Excel/DOCX report export
