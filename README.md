# LogRag 🪵🔍

LogRag is a production-grade Python CLI tool for log ingestion and Retrieval-Augmented Generation (RAG) based log analysis. It combines BM25 keyword matching with dense vector search to retrieve relevant log clusters and provides them to an LLM for structured investigation.

## ✨ Features

- **Hybrid Retrieval**: BM25 + Dense (MiniLM-L6-v2) retrieval fused with Reciprocal Rank Fusion (RRF).
- **Log Clustering**: Automatically clusters logs by message signature and time window to reduce LLM token usage.
- **Structured Investigation**: LLM-based analysis of root cause, impact, and reproduction steps.
- **Interactive Configuration**: CLI-based setup for API keys and database paths.
- **Rich Output**: Beautifully formatted terminal results with severity analysis.

## 🚀 Quick Start

### 1. Installation

LogRag uses Poetry for dependency management.

```bash
# Clone the repository
git clone <repository-url>
cd lograg

# Install dependencies
poetry install
```

### 2. Configuration

Set up your OpenAI API key and other settings:

```bash
poetry run python lograg/cli.py config
```

### 3. Usage

#### Ingest Logs
Load your logs into the local cache:
```bash
poetry run python lograg/cli.py ingest examples/sample.log
```

#### Investigate
Run an AI-powered inquiry on the ingested logs:
```bash
poetry run python lograg/cli.py investigate "login failures on api/v1"
```

## 🛠️ Project Structure

- `lograg/ingest/`: Log parsing and automated clustering logic.
- `lograg/retrieval/`: BM25, Dense (FAISS), and RRF implementations.
- `lograg/llm/`: LlamaIndex integration, prompt templates, and Pydantic schemas.
- `lograg/storage/`: SQLite-based investigation history and deduplication.
- `lograg/core/`: Main orchestration pipeline.

## 📝 License

MIT
