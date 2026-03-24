"""Tests for testpmd output parsing."""

from __future__ import annotations

from src.runner.testpmd import _parse_throughput

SAMPLE_TESTPMD_OUTPUT = """\
EAL: Detected 8 lcore(s)
Configuring Port 0 (socket 0)
Configuring Port 1 (socket 0)
Checking link statuses...
Done
testpmd> start tx_first
io packet forwarding - ports=2 - cores=2 - streams=4 - NUMA support enabled

Press enter to exit

  ---------------------- Forward statistics for port 0  ----------------------
  RX-packets: 100000000   RX-dropped: 0             RX-total: 100000000
  TX-packets: 100000000   TX-dropped: 0             TX-total: 100000000
  ---------------------- Forward statistics for port 1  ----------------------
  RX-packets: 100000000   RX-dropped: 0             RX-total: 100000000
  TX-packets: 100000000   TX-dropped: 0             TX-total: 100000000
  ---------------------- Accumulated forward statistics for all ports --------
  RX-packets: 200000000   RX-dropped: 0
  TX-packets: 200000000   TX-dropped: 0
  +++++++++++++++ Accumulated forward statistics for all ports +++++++++++++++
Bye...
"""

SAMPLE_PPS_OUTPUT = """\
Port 0: Rx-pps: 5000000   Tx-pps: 5000000
Port 1: Rx-pps: 5000000   Tx-pps: 5000000
"""


class TestParseThroughput:
    def test_parses_accumulated_stats(self) -> None:
        result = _parse_throughput(SAMPLE_TESTPMD_OUTPUT, duration=15.0)
        assert result is not None
        expected = round(200_000_000 / 15.0 / 1_000_000, 4)
        assert result == expected

    def test_fallback_to_pps(self) -> None:
        result = _parse_throughput(SAMPLE_PPS_OUTPUT, duration=10.0)
        assert result is not None
        assert result == round(10_000_000 / 1_000_000, 4)

    def test_no_data_returns_none(self) -> None:
        result = _parse_throughput("No stats here", duration=10.0)
        assert result is None

    def test_zero_duration_returns_none(self) -> None:
        result = _parse_throughput(SAMPLE_TESTPMD_OUTPUT, duration=0.0)
        assert result is None
