"""Testpmd execution and throughput measurement."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

RX_PPS_RE = re.compile(r"Rx-pps:\s+(\d+)")
RX_PACKETS_RE = re.compile(r"RX-packets:\s+(\d+)")
TX_PACKETS_RE = re.compile(r"TX-packets:\s+(\d+)")


@dataclass
class TestpmdResult:
    """Result of a testpmd throughput measurement."""

    success: bool
    throughput_mpps: float | None
    port_stats: str | None
    error: str | None
    duration_seconds: float


def run_testpmd(
    build_dir: Path,
    config: dict,
    timeout: int = 600,
) -> TestpmdResult:
    """Run testpmd in io-fwd mode and measure bi-directional throughput.

    Launches testpmd with --auto-start --tx-first, waits for forwarding
    to begin, sleeps for warmup + measurement, then stops testpmd and
    parses the accumulated forward statistics.

    Args:
        build_dir: Path to the DPDK build directory.
        config: Runner configuration dictionary.
        timeout: Maximum seconds before testpmd is killed.

    Returns:
        A TestpmdResult with throughput and raw stats.
    """
    start = time.monotonic()
    testpmd_cfg = config.get("testpmd", {})

    testpmd_bin = build_dir / "app" / "dpdk-testpmd"
    if not testpmd_bin.exists():
        return TestpmdResult(
            success=False,
            throughput_mpps=None,
            port_stats=None,
            error=f"testpmd binary not found at {testpmd_bin}",
            duration_seconds=time.monotonic() - start,
        )

    lcores = testpmd_cfg.get("lcores", "4-7")
    pci_addrs = testpmd_cfg.get("pci", ["01:00.0", "01:00.1"])
    nb_cores = int(testpmd_cfg.get("nb_cores", 2))
    rxq = int(testpmd_cfg.get("rxq", 1))
    txq = int(testpmd_cfg.get("txq", 1))
    rxd = int(testpmd_cfg.get("rxd", 1024))
    txd = int(testpmd_cfg.get("txd", 1024))
    warmup_seconds = int(testpmd_cfg.get("warmup_seconds", 5))
    measure_seconds = int(testpmd_cfg.get("measure_seconds", 10))

    eal_args = ["-l", lcores]
    for pci in pci_addrs:
        eal_args.extend(["-a", pci])

    use_sudo = testpmd_cfg.get("sudo", True)
    cmd = [
        *(["sudo"] if use_sudo else []),
        "stdbuf", "-oL",
        str(testpmd_bin),
        *eal_args,
        "--",
        f"--nb-cores={nb_cores}",
        f"--rxq={rxq}",
        f"--txq={txq}",
        f"--rxd={rxd}",
        f"--txd={txd}",
        "--auto-start",
        "--tx-first",
        "--forward-mode=io",
    ]

    logger.info("Starting testpmd: %s", " ".join(cmd))

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        return TestpmdResult(
            success=False,
            throughput_mpps=None,
            port_stats=None,
            error=f"Failed to start testpmd: {exc}",
            duration_seconds=time.monotonic() - start,
        )

    try:
        result = _measure_throughput(
            proc, warmup_seconds, measure_seconds, timeout
        )
        return TestpmdResult(
            success=result[0],
            throughput_mpps=result[1],
            port_stats=result[2],
            error=result[3],
            duration_seconds=time.monotonic() - start,
        )
    finally:
        _ensure_stopped(proc)


def _wait_for_ready(proc: subprocess.Popen, timeout: int) -> str:
    """Read testpmd output until forwarding has started."""
    output: list[str] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        output.append(line)
        logger.debug("testpmd: %s", line.rstrip())
        if "Press enter to exit" in line or "start packet forwarding" in line:
            logger.info("testpmd is forwarding")
            return "".join(output)

    return "".join(output)


def _measure_throughput(
    proc: subprocess.Popen,
    warmup: int,
    measure: int,
    timeout: int,
) -> tuple[bool, float | None, str | None, str | None]:
    """Wait for testpmd to forward, measure, then stop and parse stats.

    Returns:
        (success, throughput_mpps, stats_text, error_message)
    """
    boot_output = _wait_for_ready(proc, timeout=min(timeout, 60))
    if proc.poll() is not None:
        return (False, None, boot_output, "testpmd exited during startup")

    total_time = warmup + measure
    logger.info("Warming up %ds + measuring %ds", warmup, measure)
    time.sleep(total_time)

    # Press Enter to stop testpmd — it prints accumulated forward stats
    logger.info("Stopping testpmd after %ds", total_time)
    proc.stdin.write("\n")
    proc.stdin.flush()

    # Read remaining output (forward stats + shutdown)
    try:
        remaining_output, _ = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("testpmd did not exit after Enter, killing")
        proc.kill()
        remaining_output, _ = proc.communicate(timeout=5)

    all_output = boot_output + remaining_output

    throughput = _parse_throughput(all_output, total_time)
    if throughput is None:
        return (False, None, all_output, "Failed to parse throughput from stats")

    return (True, throughput, all_output, None)


def _parse_throughput(output: str, duration: float) -> float | None:
    """Parse accumulated forward stats and compute bi-directional Mpps.

    Looks for the 'Accumulated forward statistics for all ports' section
    and extracts RX-packets. Divides by duration to get pps.
    """
    # Try the accumulated stats line first (most reliable)
    acc_section = output.split("Accumulated forward statistics for all ports")
    if len(acc_section) >= 2:
        acc_text = acc_section[1]
        rx_match = RX_PACKETS_RE.search(acc_text)
        if rx_match and duration > 0:
            total_rx = int(rx_match.group(1))
            mpps = total_rx / duration / 1_000_000
            logger.info(
                "Throughput: %.2f Mpps (RX-packets=%d over %.0fs)",
                mpps, total_rx, duration,
            )
            return round(mpps, 4)

    # Fallback: try per-port Rx-pps if available
    matches = RX_PPS_RE.findall(output)
    if matches:
        total_pps = sum(int(m) for m in matches)
        mpps = total_pps / 1_000_000
        logger.info(
            "Throughput: %.2f Mpps (from Rx-pps, per-port: %s)",
            mpps, ", ".join(matches),
        )
        return round(mpps, 4)

    logger.warning("No throughput data found in output")
    return None


def _ensure_stopped(proc: subprocess.Popen) -> None:
    """Make sure testpmd is fully stopped."""
    if proc.poll() is not None:
        return

    try:
        proc.stdin.write("\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        logger.warning("testpmd did not exit gracefully, killing")
        proc.kill()
        proc.wait(timeout=5)
