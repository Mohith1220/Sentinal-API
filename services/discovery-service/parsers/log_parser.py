"""
Gateway access log parser.

Extracts method, host, path, status code, and timestamp from gateway log entries.
Computes last_access_at as MAX(timestamp) per endpoint.
Applies PII anonymization before persisting traffic log payload fields.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from sentinel_shared.models import EndpointRecord, AuthScheme
from sentinel_shared.normalization import normalize_path

logger = structlog.get_logger(__name__)

# PII field names that should be anonymized before persistence
PII_FIELD_NAMES = frozenset({
    "user_id", "userid", "user-id",
    "email", "email_address",
    "phone", "phone_number", "mobile",
    "ip", "ip_address", "client_ip", "remote_addr",
    "name", "full_name", "first_name", "last_name",
    "ssn", "social_security",
    "credit_card", "card_number",
    "account_number",
    "authorization",  # Auth headers may contain tokens
    "x-forwarded-for",
    "x-real-ip",
})

# Common log format patterns
# Combined Log Format: 127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326
COMBINED_LOG_PATTERN = re.compile(
    r'(?P<client_ip>\S+)\s+'       # client IP
    r'\S+\s+'                       # ident
    r'(?P<user>\S+)\s+'            # user
    r'\[(?P<timestamp>[^\]]+)\]\s+' # timestamp
    r'"(?P<method>\w+)\s+'         # method
    r'(?P<path>\S+)\s+'            # path
    r'[^"]*"\s+'                   # protocol
    r'(?P<status>\d+)\s+'          # status code
    r'(?P<size>\S+)'               # response size
)

# JSON log format (common in cloud gateways)
# Detects if a line is JSON
JSON_LOG_PATTERN = re.compile(r'^\s*\{')

# AWS ALB/API Gateway log format
# timestamp elb client:port target:port request_processing_time target_processing_time
# response_processing_time elb_status_code target_status_code received_bytes sent_bytes
# "request" "user_agent" ssl_cipher ssl_protocol target_group_arn trace_id domain_name
# chosen_cert_arn matched_rule_priority request_creation_time actions_executed redirect_url
# error_reason target_port_list target_status_code_list classification classification_reason
AWS_ALB_LOG_PATTERN = re.compile(
    r'(?P<type>\S+)\s+'
    r'(?P<timestamp>\S+)\s+'
    r'\S+\s+'                       # elb name
    r'(?P<client_ip>[^:]+):\d+\s+' # client IP:port
    r'\S+\s+'                       # target IP:port
    r'\S+\s+\S+\s+\S+\s+'         # processing times
    r'(?P<status>\d+)\s+'          # elb status
    r'\S+\s+'                       # target status
    r'\S+\s+\S+\s+'               # bytes
    r'"(?P<method>\w+)\s+'         # method
    r'(?P<scheme>\w+)://(?P<host>[^/\s]+)(?P<path>\S+)\s+' # URL
)


def anonymize_pii_value(value: str) -> str:
    """
    Replace a PII value with its SHA-256 hex digest.

    Args:
        value: The plaintext PII value.

    Returns:
        SHA-256 hex digest of the value.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def anonymize_pii_fields(data: dict[str, Any]) -> dict[str, Any]:
    """
    Anonymize PII fields in a dictionary by replacing values with SHA-256 hashes.

    Args:
        data: Dictionary potentially containing PII fields.

    Returns:
        New dictionary with PII field values replaced by their SHA-256 hashes.
    """
    result = {}
    for key, value in data.items():
        if key.lower() in PII_FIELD_NAMES and isinstance(value, str) and value:
            result[key] = anonymize_pii_value(value)
        else:
            result[key] = value
    return result


def _parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse a timestamp string into a datetime object.

    Supports multiple formats:
    - ISO 8601: 2024-01-15T10:30:00Z
    - Combined Log Format: 10/Oct/2000:13:55:36 -0700
    - Unix timestamp: 1705312200
    """
    if not timestamp_str:
        return None

    # Try ISO 8601
    try:
        # Handle Z suffix
        ts = timestamp_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except ValueError:
        pass

    # Try Unix timestamp
    try:
        ts_float = float(timestamp_str)
        return datetime.fromtimestamp(ts_float, tz=timezone.utc)
    except ValueError:
        pass

    # Try Combined Log Format: 10/Oct/2000:13:55:36 -0700
    try:
        from email.utils import parsedate_to_datetime
        # Convert CLF format to RFC 2822
        months = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }
        match = re.match(
            r'(\d+)/(\w+)/(\d+):(\d+:\d+:\d+)\s+([+-]\d{4})',
            timestamp_str
        )
        if match:
            day, month_name, year, time_part, tz_offset = match.groups()
            month = months.get(month_name, "01")
            # Build ISO format
            iso_str = f"{year}-{month}-{day}T{time_part}{tz_offset[:3]}:{tz_offset[3:]}"
            return datetime.fromisoformat(iso_str)
    except Exception:
        pass

    logger.debug("timestamp_parse_failed", timestamp=timestamp_str)
    return None


def _parse_json_log_line(line: str) -> Optional[dict]:
    """Parse a JSON-formatted log line."""
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def _extract_from_json_log(entry: dict) -> Optional[tuple[str, str, str, int, Optional[datetime]]]:
    """
    Extract (method, host, path, status_code, timestamp) from a JSON log entry.

    Handles various JSON log formats from different gateways.
    """
    # Try common field names for each attribute
    method = (
        entry.get("method") or entry.get("httpMethod") or entry.get("request_method") or
        entry.get("verb") or entry.get("http_method") or ""
    ).upper()

    host = (
        entry.get("host") or entry.get("hostname") or entry.get("domainName") or
        entry.get("domain") or entry.get("server_name") or ""
    )

    path = (
        entry.get("path") or entry.get("requestPath") or entry.get("request_path") or
        entry.get("uri") or entry.get("requestUri") or entry.get("url") or ""
    )

    # Strip query string from path
    if "?" in path:
        path = path.split("?")[0]

    status_raw = (
        entry.get("status") or entry.get("statusCode") or entry.get("status_code") or
        entry.get("responseCode") or entry.get("response_code") or 0
    )
    try:
        status_code = int(status_raw)
    except (ValueError, TypeError):
        status_code = 0

    timestamp_raw = (
        entry.get("timestamp") or entry.get("time") or entry.get("requestTime") or
        entry.get("request_time") or entry.get("@timestamp") or ""
    )
    timestamp = _parse_timestamp(str(timestamp_raw)) if timestamp_raw else None

    if not method or not path:
        return None

    return method, host, path, status_code, timestamp


def _extract_from_combined_log(line: str) -> Optional[tuple[str, str, str, int, Optional[datetime]]]:
    """Extract fields from a Combined Log Format line."""
    match = COMBINED_LOG_PATTERN.match(line)
    if not match:
        return None

    method = match.group("method").upper()
    path = match.group("path")
    status_code = int(match.group("status"))
    timestamp = _parse_timestamp(match.group("timestamp"))
    # Combined log format doesn't include host — use empty string
    host = ""

    # Strip query string
    if "?" in path:
        path = path.split("?")[0]

    return method, host, path, status_code, timestamp


def _extract_from_aws_alb_log(line: str) -> Optional[tuple[str, str, str, int, Optional[datetime]]]:
    """Extract fields from an AWS ALB log line."""
    match = AWS_ALB_LOG_PATTERN.match(line)
    if not match:
        return None

    method = match.group("method").upper()
    host = match.group("host")
    path = match.group("path")
    status_code = int(match.group("status"))
    timestamp = _parse_timestamp(match.group("timestamp"))

    # Strip query string
    if "?" in path:
        path = path.split("?")[0]

    return method, host, path, status_code, timestamp


def parse_gateway_logs(
    content: str | bytes,
    source_file_id: str = "",
    default_host: str = "unknown",
) -> list[EndpointRecord]:
    """
    Parse gateway access log content and extract endpoint records.

    Computes last_access_at as MAX(timestamp) per unique (method, host, normalized_path).
    Applies PII anonymization to log payload fields before creating records.

    Args:
        content: Raw log content as string or bytes.
        source_file_id: Optional identifier for the source file.
        default_host: Default host to use if not present in log entries.

    Returns:
        List of EndpointRecord instances, one per unique (method, host, normalized_path).
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    lines = content.splitlines()

    # Track: (method, host, normalized_path) -> (max_timestamp, status_code)
    endpoint_map: dict[tuple[str, str, str], tuple[Optional[datetime], int]] = {}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        extracted = None

        # Try JSON format first
        if JSON_LOG_PATTERN.match(line):
            entry = _parse_json_log_line(line)
            if entry:
                # Anonymize PII fields before processing
                entry = anonymize_pii_fields(entry)
                extracted = _extract_from_json_log(entry)
        else:
            # Try AWS ALB format
            extracted = _extract_from_aws_alb_log(line)
            if not extracted:
                # Try Combined Log Format
                extracted = _extract_from_combined_log(line)

        if not extracted:
            continue

        method, host, path, status_code, timestamp = extracted

        if not method or not path:
            continue

        # Use default host if not found in log
        if not host:
            host = default_host

        # Normalize path
        normalized = normalize_path(path)

        key = (method, host, normalized)

        # Track max timestamp
        existing_ts, _ = endpoint_map.get(key, (None, status_code))
        if timestamp is not None:
            if existing_ts is None or timestamp > existing_ts:
                endpoint_map[key] = (timestamp, status_code)
        elif key not in endpoint_map:
            endpoint_map[key] = (None, status_code)

    # Build endpoint records
    records: list[EndpointRecord] = []
    for (method, host, normalized_path), (last_access_at, status_code) in endpoint_map.items():
        record = EndpointRecord(
            http_method=method,
            host=host,
            normalized_path=normalized_path,
            auth_scheme=AuthScheme.UNKNOWN,
            last_access_at=last_access_at,
            source_file_id=source_file_id or None,
        )
        records.append(record)

    logger.info(
        "gateway_logs_parsed",
        source=source_file_id,
        lines_processed=len(lines),
        endpoints_found=len(records),
    )

    return records
