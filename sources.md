# Test data sources

Provenance for all public datasets used to test repi against real-world (non-synthetic) logs.
Raw files live under `tmp-ui-tests/real-logs/` (not committed).

| Dataset | Source | Format | Why it was chosen |
|---|---|---|---|
| `Linux_2k.log` | [loghub — Linux](https://github.com/logpai/loghub/blob/master/Linux/Linux_2k.log) | syslog (`Mon DD HH:MM:SS host proc[pid]: msg`) | Exercises the syslog parser path, year-less timestamps, and security-incident content (sshd auth failures, ftpd connections) — realistic "why did login fail" investigations. |
| `Apache_2k.log` | [loghub — Apache](https://github.com/logpai/loghub/blob/master/Apache/Apache_2k.log) | Apache error log (`[Day Mon DD HH:MM:SS YYYY] [level] msg`) | A common production format the parser did **not** initially support (0% timestamps, levels lost) — regression target for parser coverage. |
| `Zookeeper_2k.log` | [loghub — Zookeeper](https://github.com/logpai/loghub/blob/master/Zookeeper/Zookeeper_2k.log) | log4j (`YYYY-MM-DD HH:MM:SS,mmm - LEVEL [thread] - msg`) | Distributed-system app logs with real WARN/ERROR bursts (leader election, connection breaks) — good for multi-cluster investigation quality. |

All loghub datasets are published by the [LogPAI](https://github.com/logpai/loghub) project, collected from real systems and freely available for research purposes (see their repo for citation/terms).

Notes:
- loghub timestamps are historical (2005–2015), so relative-time queries ("last hour") won't match them; tests use explicit or entity-based queries, which also exercises the no-time-window investigation path.
- The 2k-line "_2k" samples are used instead of full datasets to keep ingest fast and LLM costs bounded.
