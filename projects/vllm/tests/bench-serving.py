"""vLLM serving benchmark — runs vllm bench serve and extracts throughput."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autoforge.plugins.protocols import DeployResult, TestResult

if TYPE_CHECKING:
    from autoforge.campaign import ProjectConfig

logger = logging.getLogger(__name__)

METRIC_PATTERNS: dict[str, str] = {
    "output_throughput_tok_s": r"Output token throughput \(tok/s\):\s+([\d.]+)",
    "total_throughput_tok_s": r"Total [Tt]oken throughput \(tok/s\):\s+([\d.]+)",
    "request_throughput_req_s": r"Request throughput \(req/s\):\s+([\d.]+)",
    "mean_ttft_ms": r"Mean TTFT \(ms\):\s+([\d.]+)",
    "median_ttft_ms": r"Median TTFT \(ms\):\s+([\d.]+)",
    "p99_ttft_ms": r"P99 TTFT \(ms\):\s+([\d.]+)",
    "mean_tpot_ms": r"Mean TPOT \(ms\):\s+([\d.]+)",
    "median_tpot_ms": r"Median TPOT \(ms\):\s+([\d.]+)",
    "p99_tpot_ms": r"P99 TPOT \(ms\):\s+([\d.]+)",
    "mean_itl_ms": r"Mean ITL \(ms\):\s+([\d.]+)",
    "p99_itl_ms": r"P99 ITL \(ms\):\s+([\d.]+)",
}


class VllmServingBenchTester:
    """Runs vllm bench serve and extracts output token throughput."""

    name = "bench-serving"

    def configure(self, project_config: ProjectConfig, runner_config: dict[str, Any]) -> None:
        cfg = runner_config.get("bench", {})
        self._num_prompts = int(cfg.get("num_prompts", 100))
        self._dataset = cfg.get("dataset_name", "random")
        self._input_len = int(cfg.get("random_input_len", 512))
        self._output_len = int(cfg.get("random_output_len", 256))
        self._max_concurrency = int(cfg.get("max_concurrency", 64))
        self._request_rate = str(cfg.get("request_rate", "inf"))
        self._result_dir = Path(cfg.get("result_dir", "/tmp/vllm-bench"))
        self._bench_cmd = cfg.get("bench_cmd", "vllm")

    def test(self, deploy_result: DeployResult, timeout: int) -> TestResult:
        host = deploy_result.target_info.get("host", "localhost")
        port = deploy_result.target_info.get("port", 8000)
        model = deploy_result.target_info.get("model", "unknown")
        container = deploy_result.target_info.get("container_name", "vllm-bench")

        self._result_dir.mkdir(parents=True, exist_ok=True)
        result_file = self._result_dir / "result.json"

        start = time.monotonic()
        try:
            cmd = [
                self._bench_cmd,
                "bench",
                "serve",
                "--backend",
                "vllm",
                "--base-url",
                f"http://{host}:{port}",
                "--model",
                model,
                "--dataset-name",
                self._dataset,
                "--num-prompts",
                str(self._num_prompts),
                "--max-concurrency",
                str(self._max_concurrency),
                "--request-rate",
                self._request_rate,
                "--save-result",
                "--result-dir",
                str(self._result_dir),
                "--result-filename",
                "result.json",
                "--percentile-metrics",
                "ttft,tpot,itl",
            ]
            if self._dataset == "random":
                cmd.extend(
                    [
                        "--random-input-len",
                        str(self._input_len),
                        "--random-output-len",
                        str(self._output_len),
                    ]
                )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.monotonic() - start

            if result.returncode != 0:
                return TestResult(
                    success=False,
                    metric_value=None,
                    results_json=None,
                    results_summary=None,
                    error=result.stderr[-1000:],
                    duration_seconds=elapsed,
                )

            metrics = _parse_results(result_file, result.stdout)
            output_tput = metrics.get("output_throughput_tok_s")
            return TestResult(
                success=True,
                metric_value=output_tput,
                results_json=metrics,
                results_summary=_format_summary(metrics),
                error=None,
                duration_seconds=elapsed,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                success=False,
                metric_value=None,
                results_json=None,
                results_summary=None,
                error="benchmark timed out",
                duration_seconds=time.monotonic() - start,
            )
        finally:
            subprocess.run(
                ["podman", "rm", "-f", container],
                capture_output=True,
                timeout=30,
            )


def _parse_results(result_file: Path, stdout: str) -> dict[str, Any]:
    if result_file.exists():
        try:
            with open(result_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    metrics: dict[str, Any] = {}
    for key, pattern in METRIC_PATTERNS.items():
        match = re.search(pattern, stdout)
        if match:
            metrics[key] = float(match.group(1))
    return metrics


def _format_summary(metrics: dict[str, Any]) -> str:
    tput = metrics.get("output_throughput_tok_s", 0)
    ttft = metrics.get("median_ttft_ms", 0)
    tpot = metrics.get("median_tpot_ms", 0)
    return f"{tput:.1f} tok/s output | TTFT {ttft:.1f}ms | TPOT {tpot:.2f}ms"
