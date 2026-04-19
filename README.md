# repi — Codebase Impact Engine

**repi** (REPO Impact) is a distributable Python CLI tool that parses codebases into a persistent **Code Property Graph (CPG)**. 

By mapping out functions, classes, and call sites into a local graph database, **repi** provides the foundation for deep codebase analysis, blast radius detection, and dependency tracking.

## Features

- ⚡ **Persistent Graph**: All data is stored in an embedded [Kuzu](https://kuzudb.com/) graph database in your local `.repi` folder. No server required.
- 🌳 **AST-Powered**: Uses Tree-sitter for high-accuracy parsing of code structures.
- 🐍 **Language Support**: Optimized for **Python**, with full support for **TypeScript**, **TSX**, and **JavaScript**.
- 🛠️ **Developer First**: Designed for humans. Deterministic IDs, clean CLI output, and JSON support.

## Installation

```bash
# Clone and install via poetry
git clone https://github.com/vrun/repi.git
cd repi
poetry install
```

## Quick Start

### 1. Scan a Repository
Point **repi** at any Python or TS/JS project to build its impact graph.
```bash
repi scan ./my-project
```

### 2. Inspect Nodes
List all extracted functions, classes, or methods.
```bash
repi nodes ./my-project --type function
```

### 3. View Graph Stats
Check the depth and complexity of your codebase.
```bash
repi graph ./my-project
```

## How it Works

1. **Extraction**: Identifies named entities (functions, classes) and call sites using Tree-sitter.
2. **Identification**: Generates deterministic IDs based on file path, name, and position.
3. **Resolution**: Links call sites to their corresponding definitions within the codebase.
4. **Persistence**: Stores the final nodes and edges in a high-performance graph database.

## Architecture

- **`impact_engine/extractor`**: Tree-sitter based analysis logic.
- **`impact_engine/graph`**: Kuzu database schema and graph construction.
- **`impact_engine/cli.py`**: User interface powered by `typer` and `rich`.

## License
MIT
