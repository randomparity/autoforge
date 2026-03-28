"""Core perf profiling: capture, folded-stack parsing, counter parsing."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from autoforge.perf.arch import COMMON_EVENTS, load_arch_profile

logger = logging.getLogger(__name__)

PERF_TIMEOUT_MARGIN = 30  # extra seconds beyond duration for perf to finish


@dataclass
class PerfCaptureResult:
    """Result of a perf profiling capture."""

    success: bool
    folded_stacks: dict[str, int] = field(default_factory=dict)
    counters: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0


def _build_cmd(args: list[str], *, sudo: bool) -> list[str]:
    if sudo:
        return ["sudo", *args]
    return args


def _run_concurrent_perf(
    record_cmd: list[str],
    stat_cmd: list[str],
    timeout: float,
) -> tuple[int, bytes, int, bytes]:
    """Spawn perf record and perf stat concurrently and collect their output.

    Args:
        record_cmd: Full argv for ``perf record``.
        stat_cmd: Full argv for ``perf stat``.
        timeout: Maximum seconds to wait for both processes to finish.

    Returns:
        ``(record_returncode, record_stderr, stat_returncode, stat_stderr)``.

    Raises:
        OSError: If either process fails to start (the other is killed first).
        subprocess.TimeoutExpired: If the deadline elapses before both finish.
    """
    record_proc = subprocess.Popen(
        record_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stat_proc = subprocess.Popen(
            stat_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        record_proc.kill()
        record_proc.wait(timeout=10)
        raise

    try:
        deadline = time.monotonic() + timeout
        _, record_stderr = record_proc.communicate(timeout=timeout)
        remaining = max(5.0, deadline - time.monotonic())
        _, stat_stderr = stat_proc.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        record_proc.kill()
        stat_proc.kill()
        record_proc.wait(timeout=10)
        stat_proc.wait(timeout=10)
        raise

    return record_proc.returncode, record_stderr, stat_proc.returncode, stat_stderr


def _extract_folded_stacks(
    perf_data: Path,
    output_dir: Path,
    *,
    sudo: bool,
    timeout: float,
) -> tuple[dict[str, int], str | None]:
    """Run ``perf script``, fold the stacks, and write them to disk.

    Args:
        perf_data: Path to the ``perf.data`` file produced by ``perf record``.
        output_dir: Directory where ``stacks.folded`` will be written.
        sudo: Whether to prefix ``perf script`` with ``sudo``.
        timeout: Maximum seconds to allow ``perf script`` to run.

    Returns:
        ``(stacks, None)`` on success, or ``({}, error_message)`` on failure.
    """
    script_cmd = _build_cmd(["perf", "script", "-i", str(perf_data)], sudo=sudo)
    script_result = subprocess.run(
        script_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    logger.debug(
        "perf script rc=%d, stdout=%d bytes, stderr=%s",
        script_result.returncode,
        len(script_result.stdout),
        script_result.stderr[:300],
    )
    if script_result.returncode != 0:
        return {}, f"perf script failed: {script_result.stderr[:500]}"

    stacks = fold_stacks(script_result.stdout)
    try:
        write_folded(stacks, output_dir / "stacks.folded")
    except OSError as exc:
        return {}, f"Failed to write folded stacks: {exc}"

    return stacks, None


def _build_perf_cmds(
    pid: int,
    duration: int,
    perf_data: Path,
    *,
    arch: str | None,
    frequency: int,
    sudo: bool,
    cpus: str | None,
) -> tuple[list[str], list[str]]:
    """Build argv lists for concurrent perf record + perf stat invocations.

    Args:
        pid: Target process ID (used when ``cpus`` is None).
        duration: Capture duration in seconds.
        perf_data: Output path for ``perf record`` data file.
        arch: Architecture key for event selection; auto-detected if None.
        frequency: Sampling frequency in Hz.
        sudo: Whether to prefix commands with ``sudo``.
        cpus: CPU list for system-wide profiling (e.g. ``"4-12"``).

    Returns:
        ``(record_cmd, stat_cmd)`` as argv lists.
    """
    profile = load_arch_profile(arch)
    events = list(profile.get("events", {}).values()) or COMMON_EVENTS

    if cpus:
        target_args: list[str] = ["-a", "-C", cpus]
        logger.info("Profiling CPUs %s (system-wide on those cores)", cpus)
    else:
        target_args = ["-p", str(pid)]

    record_cmd = _build_cmd(
        [
            "perf",
            "record",
            "--call-graph",
            "dwarf,16384",
            "-F",
            str(frequency),
            *target_args,
            "-o",
            str(perf_data),
            "--",
            "sleep",
            str(duration),
        ],
        sudo=sudo,
    )
    stat_cmd = _build_cmd(
        [
            "perf",
            "stat",
            "-e",
            ",".join(events),
            *target_args,
            "--",
            "sleep",
            str(duration),
        ],
        sudo=sudo,
    )
    return record_cmd, stat_cmd


def profile_pid(
    pid: int,
    duration: int,
    output_dir: Path,
    *,
    arch: str | None = None,
    frequency: int = 99,
    sudo: bool = False,
    cpus: str | None = None,
) -> PerfCaptureResult:
    """Capture perf record + perf stat against a running process.

    Args:
        pid: Target process ID.
        duration: Capture duration in seconds.
        output_dir: Directory for artifacts (perf.data, folded stacks).
        arch: Architecture key for event selection. Auto-detected if None.
        frequency: Sampling frequency in Hz.
        sudo: Whether to run perf commands with sudo.
        cpus: CPU list for system-wide profiling (e.g. "4-12"). When set,
            uses -a -C instead of -p to capture all threads on those cores.

    Returns:
        PerfCaptureResult with folded stacks and counter data.
    """
    start = time.monotonic()

    if not shutil.which("perf"):
        return PerfCaptureResult(
            success=False,
            error="perf binary not found in PATH",
            duration_seconds=time.monotonic() - start,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    perf_data = output_dir / "perf.data"
    timeout = duration + PERF_TIMEOUT_MARGIN

    record_cmd, stat_cmd = _build_perf_cmds(
        pid, duration, perf_data, arch=arch, frequency=frequency, sudo=sudo, cpus=cpus
    )

    logger.info("Starting perf record (pid=%d, %ds, %dHz)", pid, duration, frequency)
    try:
        record_rc, record_stderr, stat_rc, stat_stderr = _run_concurrent_perf(
            record_cmd, stat_cmd, timeout
        )
    except OSError as exc:
        return PerfCaptureResult(
            success=False,
            error=str(exc),
            duration_seconds=time.monotonic() - start,
        )
    except subprocess.TimeoutExpired:
        return PerfCaptureResult(
            success=False,
            error="perf timed out",
            duration_seconds=time.monotonic() - start,
        )

    record_stderr_text = record_stderr.decode(errors="replace")
    stat_stderr_text = stat_stderr.decode(errors="replace")

    logger.debug("perf record rc=%d stderr: %s", record_rc, record_stderr_text[:500])
    logger.debug("perf stat rc=%d stderr: %s", stat_rc, stat_stderr_text[:500])

    if perf_data.exists():
        logger.debug("perf.data size: %d bytes", perf_data.stat().st_size)
    else:
        logger.warning("perf.data not found at %s", perf_data)

    if record_rc != 0:
        return PerfCaptureResult(
            success=False,
            error=f"perf record failed: {record_stderr_text[:500]}",
            duration_seconds=time.monotonic() - start,
        )

    if stat_rc != 0:
        # Non-fatal: perf stat counters are supplementary to perf record.
        # The profile result is still usable from the recorded data alone.
        logger.warning(
            "perf stat failed (rc=%d), continuing without counters: %s",
            stat_rc,
            stat_stderr_text[:300],
        )

    stacks, error = _extract_folded_stacks(perf_data, output_dir, sudo=sudo, timeout=timeout)
    if error is not None:
        return PerfCaptureResult(
            success=False,
            error=error,
            duration_seconds=time.monotonic() - start,
        )

    counters = parse_perf_stat(stat_stderr.decode(errors="replace"))

    logger.info(
        "Profiling complete: %d unique stacks, %d counters",
        len(stacks),
        len(counters),
    )
    return PerfCaptureResult(
        success=True,
        folded_stacks=stacks,
        counters=counters,
        duration_seconds=time.monotonic() - start,
    )


def _flush_frames(frames: list[str], stacks: dict[str, int]) -> None:
    """Flush accumulated frames into the folded-stacks dict and clear frames."""
    if frames:
        stack_key = ";".join(reversed(frames))
        stacks[stack_key] = stacks.get(stack_key, 0) + 1
        frames.clear()


def fold_stacks(perf_script_output: str) -> dict[str, int]:
    """Parse perf script output into folded stacks.

    Args:
        perf_script_output: Raw text from `perf script`.

    Returns:
        Dict mapping semicolon-delimited stack strings to sample counts.
    """
    stacks: dict[str, int] = {}
    current_frames: list[str] = []

    for line in perf_script_output.splitlines():
        stripped = line.strip()

        if not stripped:
            _flush_frames(current_frames, stacks)
            continue

        if stripped.startswith(("(", "#")):
            continue

        # Frame lines start with hex address
        parts = stripped.split(None, 1)
        if len(parts) >= 2 and _is_hex(parts[0]):
            raw = parts[1].split("(")[0].strip()
            # Strip offset like "+0x20" to get the bare symbol name
            symbol = raw.split("+")[0] if raw else parts[0]
            current_frames.append(symbol)

    # Handle last record if no trailing blank line
    _flush_frames(current_frames, stacks)

    return stacks


def _is_hex(s: str) -> bool:
    try:
        int(s, 16)
    except ValueError:
        return False
    return True


_STAT_LINE_RE = re.compile(r"^\s*([\d,]+)\s+(\S+)")


def parse_perf_stat(raw_output: str) -> dict[str, float]:
    """Parse perf stat text output into a dict of event values.

    Args:
        raw_output: Raw stderr text from `perf stat`.

    Returns:
        Dict mapping event names to numeric values.
    """
    counters: dict[str, float] = {}
    for line in raw_output.splitlines():
        match = _STAT_LINE_RE.match(line)
        if match:
            value_str = match.group(1).replace(",", "")
            event_name = match.group(2)
            try:
                counters[event_name] = float(value_str)
            except ValueError:
                continue
    return counters


def write_folded(stacks: dict[str, int], path: Path) -> None:
    """Write folded stacks in Brendan Gregg format.

    Each line: 'frame1;frame2;frame3 count'
    """
    with open(path, "w") as f:
        for stack, count in sorted(stacks.items(), key=lambda x: -x[1]):
            f.write(f"{stack} {count}\n")
