#!/usr/bin/env python3

import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta
import os
import urllib.request
import sys

# ======================================================================
# CONFIGURATION
# ======================================================================

DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() in ("true", "1", "yes", "on")

TOKEN_COUNT = int(os.environ.get("TOKEN_COUNT", "").strip() or "4000")

LOG_LINES = int(os.environ.get("MAX_LINES", "").strip() or "10000")
HOURS_TO_ANALYZE = int(os.environ.get("MAX_HOURS", "").strip() or "24")

LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "").strip() or "sk-dummy"
LITELLM_URL = (os.environ.get("LITELLM_ADDRESS", "").strip().rstrip("/") or "http://localhost:4000") + "/v1/chat/completions"

LITELLM_MODEL = os.environ.get("MODEL_NAME", "").strip() or "gpt-4o"

# ======================================================================
# HELPERS
# ======================================================================

def run_command(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            f"{result.stderr}"
        )

    return result.stdout

def get_logs():
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is missing!")

    req = urllib.request.Request(
        "http://supervisor/core/logs",
        headers={
            "Authorization": f"Bearer {token}"
        }
    )

    with urllib.request.urlopen(req) as response:
        return response.read().decode()

def remove_ansi(text):
    """
    Remove ANSI terminal color/control sequences.
    """
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# HA Core timestamp format:
# 2026-10-03 10:54:32.070

TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2}\.\d+)"
)


def parse_timestamp(line):
    match = TIMESTAMP_RE.match(line)

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(1),
            "%Y-%m-%d %H:%M:%S.%f"
        )
    except ValueError:
        return None

def filter_after_last_restart(lines):
    """
    Keep only timestamped Home Assistant Core logs after the
    last shutdown marker. Exclude Supervisor/s6 lifecycle messages.
    """

    restart_marker = "Home Assistant Core service shutdown"
    restart_index = None

    # Find the last Core shutdown marker
    for index, line in enumerate(lines):
        if restart_marker in line:
            restart_index = index

    if restart_index is None:
        return lines
#        raise RuntimeError(
#            "Could not find the last Home Assistant Core shutdown marker. "
#            "Cannot safely determine the current session's logs."
#        )

    # Find the first timestamped Core log entry after shutdown
    first_core_index = None

    for index in range(restart_index + 1, len(lines)):
        line = remove_ansi(lines[index])

        if parse_timestamp(line) is not None:
            first_core_index = index
            break

    if first_core_index is None:
        raise RuntimeError(
            "No timestamped Core log entries found after the last shutdown."
        )

    # Keep only timestamped Core log lines and their continuation lines.
    filtered_lines = []
    found_core_entry = False

    for line in lines[first_core_index:]:
        clean_line = remove_ansi(line)

        if parse_timestamp(clean_line) is not None:
            found_core_entry = True
            filtered_lines.append(line)

        elif found_core_entry and clean_line[:1].isspace():
            # Preserve indented continuation lines, such as tracebacks.
            filtered_lines.append(line)

    print(
        f"Last shutdown marker: raw line {restart_index + 1:,}"
    )
    print(
        f"First Core entry: raw line {first_core_index + 1:,}"
    )
    print(
        f"Lines retained after restart: {len(filtered_lines):,}"
    )
    print()

    return filtered_lines

# ======================================================================
# LOG PARSING
# ======================================================================

def parse_core_logs(lines):
    """
    Parse HA Core logs.

    Each timestamped line starts a new log entry.

    For multiline Python tracebacks:
      - keep the original log line
      - discard traceback frames
      - keep only the final exception/error line
    """

    entries = []

    current = None
    traceback_lines = []

    for raw_line in lines:

        line = remove_ansi(raw_line).rstrip()

        if not line:
            continue

        timestamp = parse_timestamp(line)

        # --------------------------------------------------------------
        # New log entry
        # --------------------------------------------------------------

        if timestamp is not None:

            # Finish previous entry
            if current is not None:

                if traceback_lines:
                    exception_line = find_exception_line(
                        traceback_lines
                    )

                    if exception_line:
                        current["lines"].append(exception_line)

                entries.append(current)

            current = {
                "timestamp": timestamp,
                "lines": [line],
            }

            traceback_lines = []

            continue

        # --------------------------------------------------------------
        # Continuation of previous entry
        # --------------------------------------------------------------

        if current is None:
            continue

        stripped = line.strip()

        if not stripped:
            continue

        traceback_lines.append(stripped)

    # Finish final entry
    if current is not None:

        if traceback_lines:
            exception_line = find_exception_line(
                traceback_lines
            )

            if exception_line:
                current["lines"].append(exception_line)

        entries.append(current)

    return entries


def find_exception_line(lines):
    """
    Find the useful final exception from a Python traceback.

    We deliberately discard:
      File "...", line ...
      source-code lines
      Traceback (most recent call last):

    and retain the final exception such as:

      httpcore.ConnectError: All connection attempts failed
      TimeoutError: ...
      ValueError: ...
      ButtonCardJSTemplateError: ...
    """

    candidates = []

    for line in lines:

        stripped = line.strip()

        if not stripped:
            continue

        # Python traceback machinery
        if stripped == "Traceback (most recent call last):":
            continue

        # Python stack frame
        if stripped.startswith("File "):
            continue

        # Common source-code lines
        if (
            stripped.startswith("return ")
            or stripped.startswith("await ")
            or stripped.startswith("raise ")
            or stripped.startswith("yield ")
            or stripped.startswith("with ")
            or stripped.startswith("async ")
            or stripped.startswith("self.")
            or stripped.startswith("response =")
            or stripped.startswith("resp =")
            or stripped.startswith("result =")
        ):
            continue

        # --------------------------------------------------------------
        # Exception class + message
        #
        # Examples:
        #   httpcore.ConnectError: All connection attempts failed
        #   ValueError: invalid value
        #   TimeoutError: timed out
        #   ButtonCardJSTemplateError: SyntaxError: ...
        # --------------------------------------------------------------

        if re.match(
            r"^[A-Za-z_][\w.]*\.[A-Za-z_][\w]*(?::\s*.*)?$",
            stripped
        ):
            candidates.append(stripped)
            continue

        if re.match(
            r"^[A-Za-z_][\w]*(?:Error|Exception)"
            r"(?:\s*:\s*.*)?$",
            stripped
        ):
            candidates.append(stripped)
            continue

    # Only keep the final exception.
    if candidates:
        return candidates[-1]

    return None


# ======================================================================
# TIME FILTERING
# ======================================================================

def filter_last_24_hours(entries):
    cutoff = datetime.now() - timedelta(
        hours=HOURS_TO_ANALYZE
    )

    return [
        entry
        for entry in entries
        if entry["timestamp"] >= cutoff
    ]


# ======================================================================
# SEVERITY
# ======================================================================

def get_severity(entry):
    text = " ".join(entry["lines"])

    match = re.search(
        r"\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b",
        text
    )

    if match:
        return match.group(1)

    return "UNKNOWN"


# ======================================================================
# DUPLICATE CONSOLIDATION
# ======================================================================

def normalize_message(text):
    """
    Normalize variable values so repeated messages can be grouped.
    """

    text = text.strip()

    # Remove timestamp
    text = re.sub(
        r"^\d{4}-\d{2}-\d{2} "
        r"\d{2}:\d{2}:\d+\.\d+\s*",
        "",
        text,
    )

    # IP addresses
    text = re.sub(
        r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
        "<IP>",
        text,
    )

    # Long hexadecimal IDs
    text = re.sub(
        r"\b[0-9a-fA-F]{8,}\b",
        "<ID>",
        text,
    )

    # Standalone numbers
    text = re.sub(
        r"\b\d+\b",
        "<N>",
        text,
    )

    # Normalize whitespace
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def consolidate_entries(entries):
    """
    Group identical/near-identical messages.
    """

    groups = {}

    for entry in entries:

        # The first line is always the useful HA log message.
        main_message = entry["lines"][0]

        normalized = normalize_message(main_message)

        if normalized not in groups:
            groups[normalized] = {
                "count": 0,
                "severity": get_severity(entry),
                "timestamp": entry["timestamp"],
                "lines": entry["lines"].copy(),
            }

        groups[normalized]["count"] += 1

        # If this occurrence has an exception line and the stored
        # version doesn't, keep it.
        if len(entry["lines"]) > 1:
            if len(groups[normalized]["lines"]) == 1:
                groups[normalized]["lines"].append(
                    entry["lines"][-1]
                )

    return list(groups.values())


# ======================================================================
# OUTPUT CLEANUP
# ======================================================================

def clean_to_ascii(text):
    """
    Remove characters that may unnecessarily increase the prompt size.
    """

    return text.encode(
        "ascii",
        errors="ignore"
    ).decode("ascii")

def clean_analysis_output(text):
    """
    Convert LiteLLM output to plain ASCII for terminal display.
    """
    return text.encode(
        "ascii",
        errors="ignore"
    ).decode("ascii")

def format_compact_entry(item):
    """
    Convert a consolidated HA log entry into a compact,
    AI-friendly single line.
    """

    severity = item["severity"]
    count = item["count"]

    # --------------------------------------------------------------
    # Parse the original HA log line
    #
    # Example:
    # 2026-10-03 10:54:32.070 ERROR (MainThread)
    # [homeassistant] Error doing job: ...
    # --------------------------------------------------------------

    line = item["lines"][0]

    match = re.match(
        r"^\d{4}-\d{2}-\d{2} "
        r"\d{2}:\d{2}:\d{2}\.\d+\s+"
        r"\w+\s+"
        r"(?:\([^)]*\)\s+)?"
        r"\[([^\]]+)\]\s*"
        r"(.*)$",
        line,
    )

    if match:
        component = match.group(1)
        message = match.group(2).strip()
    else:
        component = "unknown"
        message = line.strip()

    # --------------------------------------------------------------
    # Remove common HA prefixes from component names
    # --------------------------------------------------------------

    for prefix in (
        "custom_components.",
        "homeassistant.components.",
        "homeassistant.helpers.",
        "homeassistant.",
    ):
        if component.startswith(prefix):
            component = component[len(prefix):]
            break

    # --------------------------------------------------------------
    # If there is an exception, use the exception as the message.
    # Otherwise use the original message.
    # --------------------------------------------------------------

    if len(item["lines"]) > 1:
        exception = item["lines"][-1].strip()

        if (
            re.match(
                r"^[A-Za-z_][\w.]*\.[A-Za-z_][\w]*:",
                exception,
            )
            or re.match(
                r"^[A-Za-z_][\w]*(?:Error|Exception):",
                exception,
            )
        ):
            message = exception

    # --------------------------------------------------------------
    # Remove unnecessary details
    # --------------------------------------------------------------

    # Chrome / Windows client information
    message = re.sub(
        r" from Chrome [^ ]+ on Windows [^ ]+",
        "",
        message,
    )

    # Collapse whitespace
    message = re.sub(
        r"\s+",
        " ",
        message,
    ).strip()

    # --------------------------------------------------------------
    # Limit an individual message.
    # One huge log entry shouldn't consume the entire context.
    # --------------------------------------------------------------

    MAX_MESSAGE_LENGTH = 180

    if len(message) > MAX_MESSAGE_LENGTH:
        message = (
            message[:MAX_MESSAGE_LENGTH - 3]
            + "..."
        )

    return (
        f"{severity} x{count} | "
        f"{component} | "
        f"{message}"
    )

def limit_text(text):
    """
    Approximate token limit.

    Roughly 4 characters per token.
    """

    max_chars = TOKEN_COUNT * 4

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "\n...[TRUNCATED]..."

def wrap_console_text(text, width=100):
    """
    Wrap long lines so console output remains readable.

    Preserves Markdown structure reasonably well while preventing
    extremely long lines from being hard-wrapped by the terminal.
    """

    import textwrap

    output = []

    for line in text.splitlines():

        # Keep empty lines
        if not line.strip():
            output.append("")
            continue

        # Don't wrap fenced code markers
        if line.strip().startswith("```"):
            output.append(line)
            continue

        # Wrap normal text while preserving indentation
        indent = len(line) - len(line.lstrip())
        prefix = line[:indent]
        content = line[indent:]

        wrapped = textwrap.wrap(
            content,
            width=max(20, width - indent),
            break_long_words=False,
            break_on_hyphens=False,
        )

        if not wrapped:
            output.append(line)
            continue

        output.append(prefix + wrapped[0])

        for continuation in wrapped[1:]:
            output.append(prefix + continuation)

    return "\n".join(output)


# ======================================================================
# MAIN
# ======================================================================

def main():

    print("=" * 70)
    print("HOME ASSISTANT CORE LOG ANALYSIS")
    print("=" * 70)
    print()

    # --------------------------------------------------------------
    # Collect Core logs
    # --------------------------------------------------------------
    
    output = "\n".join(get_logs().splitlines()[-LOG_LINES:])

    raw_lines = output.splitlines()

    # --------------------------------------------------------------
    # Keep only logs after the last Core restart
    # --------------------------------------------------------------

    raw_lines = filter_after_last_restart(raw_lines)

    # --------------------------------------------------------------
    # Parse
    # --------------------------------------------------------------

    entries = parse_core_logs(raw_lines)

    # --------------------------------------------------------------
    # Filter last 24 hours
    # --------------------------------------------------------------

    entries = filter_last_24_hours(entries)

    # --------------------------------------------------------------
    # Severity counts
    # --------------------------------------------------------------

    severity_counts = Counter(
        get_severity(entry)
        for entry in entries
    )

    print("Severity counts:")
    print(f"  CRITICAL: {severity_counts['CRITICAL']:,}")
    print(f"  ERROR:    {severity_counts['ERROR']:,}")
    print(f"  WARNING:  {severity_counts['WARNING']:,}")
    print(f"  INFO:     {severity_counts['INFO']:,}")
    print(f"  DEBUG:    {severity_counts['DEBUG']:,}")
    print()

    # --------------------------------------------------------------
    # Consolidate duplicates
    # --------------------------------------------------------------

    consolidated = consolidate_entries(entries)

    # --------------------------------------------------------------
    # Build compact stream
    # --------------------------------------------------------------

    print("=" * 70)
    print("COMPACT LOG STREAM")
    print("=" * 70)

    compact_lines = []

    # Most important messages first
    consolidated.sort(
        key=lambda x: (
            {
                "CRITICAL": 0,
                "ERROR": 1,
                "WARNING": 2,
                "INFO": 3,
                "DEBUG": 4,
            }.get(x["severity"], 5),
            -x["count"],
        )
    )

    for item in consolidated:
        compact_lines.append(
            format_compact_entry(item)
        )

    compact_text = "\n".join(compact_lines)

    compact_text = limit_text(compact_text)

    print(compact_text)

    

    # --------------------------------------------------------------
    # DRY RUN
    # --------------------------------------------------------------

    if DRY_RUN:
        print()
        print("=" * 70)

        print("DRY_RUN=True")
        print("LiteLLM request was NOT sent.")

        print("-" * 70)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        print(f"Analysis time: {current_time}")
        
        return

    # --------------------------------------------------------------
    # LiteLLM
    # --------------------------------------------------------------

    # This section can be enabled once the compact output looks good.

    import json
    import urllib.request


    system_prompt = """You are an expert Home Assistant log analyst.

Analyze the supplied Home Assistant Core logs.

Identify:
- important errors
- recurring warnings
- likely root causes
- network/device/integration problems
- configuration or automation problems
- issues that appear transient versus persistent

Prioritize issues by practical significance.

Be concise and avoid repeating the raw logs.

OUTPUT FORMAT:
Return plain text only.
Use simple headings and bullet points when useful.
Do NOT use Markdown tables.
Do NOT use ASCII tables.
Do NOT use any table-like formatting.
Do NOT use code blocks.
Do NOT use Markdown formatting.
Do NOT use decorative characters.
Do NOT use Unicode symbols.
Keep lines reasonably short.

Focus on actionable findings and avoid unnecessary explanation.
"""

    user_prompt = f"""Home Assistant Core logs from the last {HOURS_TO_ANALYZE} hours:

{compact_text}
"""

    payload = {
        "model": LITELLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": 0.1,
    }

    request = urllib.request.Request(
        LITELLM_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {LITELLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    print()
    print("=" * 70)
    print("LITELLM ANALYSIS")
    print("=" * 70)
    print()

    analysis = result["choices"][0]["message"]["content"]
    analysis = clean_analysis_output(analysis)
    print(
       wrap_console_text(
           analysis,
           width=100,
       )
    )
    
    print("-" * 70)
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"Analysis time: {current_time}")

if __name__ == "__main__":
    main()
