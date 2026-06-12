"""Signature masking coverage against real-world log lines (LogHub-style).

Masking exists to collapse high-cardinality tokens (IDs, IPs, counts) so logs
cluster by template. But blanket digit-masking also destroyed meaningful,
low-cardinality numbers — HTTP status codes, protocol versions, digits inside
identifiers — making signatures unreadable and occasionally splitting clusters.
"""
from repi.ingestion.log_chunker import get_signature


# ── High-cardinality tokens still mask ───────────────────────────────────────

def test_pids_and_counts_masked():
    sig = get_signature("sshd(pam_unix)[19939]: authentication failure; uid=0 euid=0")
    assert "[<NUM>]" in sig
    assert "uid=<NUM>" in sig
    assert "19939" not in sig


def test_uuid_and_hex_masked():
    sig = get_signature("request 550e8400-e29b-41d4-a716-446655440000 failed at 0xDEADBEEF")
    assert "<UUID>" in sig
    assert "<HEX>" in sig


def test_trailing_instance_digits_masked_so_nodes_cluster_together():
    # node1/node2/node3 must produce the SAME signature
    assert get_signature("connection lost to node1") == get_signature("connection lost to node2")
    assert "<NUM>" in get_signature("connection lost to node1")


# ── IPv4 collapses to one readable token ─────────────────────────────────────

def test_ipv4_masked_as_single_ip_token():
    sig = get_signature("connection from 218.188.2.4 () at Sun Jul 10 03:55:14 2005")
    assert "<IP>" in sig
    assert "<NUM>.<NUM>" not in sig


def test_two_hosts_same_signature():
    a = get_signature("Received connection request /10.10.34.11:45307")
    b = get_signature("Received connection request /10.10.34.12:45308")
    assert a == b


# ── Meaningful numbers survive ───────────────────────────────────────────────

def test_http_status_code_preserved_in_access_log():
    sig = get_signature('66.249.66.1 - - "GET /index.html HTTP/1.1" 404 2326')
    assert "404" in sig
    assert "HTTP/1.1" in sig
    assert "2326" not in sig  # response bytes are high-cardinality


def test_status_keyword_preserves_code():
    sig = get_signature("upstream returned status 502 for request 8812345")
    assert "status 502" in sig
    assert "8812345" not in sig


def test_mid_identifier_digits_preserved():
    sig = get_signature("jk2_init() Found child 6725 in scoreboard slot 10")
    assert "jk2_init()" in sig
    assert "6725" not in sig
    assert "slot <NUM>" in sig


# ── Stability: same template, different values → same signature ──────────────

def test_apache_template_clusters_across_values():
    a = get_signature("mod_jk child workerEnv in error state 6")
    b = get_signature("mod_jk child workerEnv in error state 7")
    assert a == b


def test_api_version_segment_preserved():
    sig = get_signature("GET /api/v1/users/profile took 8231ms for user 99812")
    assert "/api/v1/" in sig
    assert "8231" not in sig and "99812" not in sig
