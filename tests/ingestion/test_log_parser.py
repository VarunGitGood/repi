"""Parser coverage for real-world log formats (LogHub-style samples).

These formats previously fell through to the plain-message fallback, which
stored every line as level=INFO with no timestamp — silently disabling
time-window and level filtering for real logs.
"""
from datetime import datetime, timedelta

from repi.ingestion.log_parser import parse_log_line


# ── Synthetic / app-log format (regression) ──────────────────────────────────

def test_iso_z_format_still_parses():
    p = parse_log_line("2026-05-01T21:50:00Z [ERROR] DB connection refused")
    assert p.level == "ERROR"
    assert p.message == "DB connection refused"
    assert p.parsed_timestamp == datetime(2026, 5, 1, 21, 50, 0)


def test_json_format_still_parses():
    p = parse_log_line('{"timestamp": "2026-05-01T21:50:00Z", "level": "warn", "message": "slow query"}')
    assert p.level == "WARN"
    assert p.message == "slow query"
    assert p.parsed_timestamp == datetime(2026, 5, 1, 21, 50, 0)


# ── log4j / logback (e.g. Zookeeper, Kafka) ──────────────────────────────────

def test_log4j_comma_millis_timestamp_and_level():
    p = parse_log_line(
        "2015-07-29 17:41:44,747 - INFO  [QuorumPeer[myid=1]:FastLeaderElection@774] - Notification time out: 3200"
    )
    assert p.level == "INFO"
    assert p.parsed_timestamp == datetime(2015, 7, 29, 17, 41, 44, 747000)


def test_log4j_warn_level_not_downgraded_to_info():
    p = parse_log_line(
        "2015-07-29 17:41:45,000 - WARN  [SendWorker:188978561024:QuorumCnxManager$SendWorker@679] - Interrupted while waiting for message"
    )
    assert p.level == "WARN"
    assert p.parsed_timestamp == datetime(2015, 7, 29, 17, 41, 45)


# ── Syslog (e.g. sshd) ────────────────────────────────────────────────────────

def test_syslog_timestamp_extracted():
    p = parse_log_line("Dec 10 06:55:46 LabSZ sshd[24200]: Invalid user webmaster from 173.234.31.186")
    assert p.parsed_timestamp is not None
    assert (p.parsed_timestamp.month, p.parsed_timestamp.day) == (12, 10)
    assert p.parsed_timestamp.hour == 6
    assert p.message == "LabSZ sshd[24200]: Invalid user webmaster from 173.234.31.186"
    assert p.level == "INFO"


def test_syslog_year_inference_never_lands_in_future():
    p = parse_log_line("Dec 10 06:55:46 LabSZ sshd[24200]: Invalid user webmaster from 173.234.31.186")
    assert p.parsed_timestamp <= datetime.utcnow() + timedelta(days=1)


def test_syslog_single_digit_day():
    p = parse_log_line("Jun  9 11:42:01 host cron[123]: (root) CMD (run-parts /etc/cron.hourly)")
    assert p.parsed_timestamp is not None
    assert (p.parsed_timestamp.month, p.parsed_timestamp.day) == (6, 9)


def test_syslog_error_body_tagged_error():
    p = parse_log_line(
        "Dec 10 07:28:03 LabSZ sshd[24245]: error: maximum authentication attempts exceeded for root [preauth]"
    )
    assert p.level == "ERROR"


# ── Apache/nginx access log ──────────────────────────────────────────────────

def test_access_log_timestamp_normalised_to_utc():
    p = parse_log_line('66.249.66.1 - - [10/Oct/2025:13:55:36 -0700] "GET /index.html HTTP/1.1" 200 2326')
    assert p.parsed_timestamp == datetime(2025, 10, 10, 20, 55, 36)
    assert p.parsed_timestamp.tzinfo is None
    assert p.message.startswith("66.249.66.1 ")
    assert '"GET /index.html HTTP/1.1" 200 2326' in p.message


# ── Fallback ─────────────────────────────────────────────────────────────────

def test_unknown_format_falls_back_to_plain_message():
    p = parse_log_line("completely unstructured line with no timestamp")
    assert p.level == "INFO"
    assert p.parsed_timestamp is None
    assert p.message == "completely unstructured line with no timestamp"
