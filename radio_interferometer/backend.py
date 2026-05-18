"""Process-isolated streaming and correlation backend."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from multiprocessing import Event, Process, Queue, get_context
from queue import Empty, Full
from time import monotonic
from typing import Any

from .correlator import CorrelatorConfig, CorrelatorResult, FXCorrelator
from .sources import (
    B210ReadOverflow,
    B210SoapySource,
    ObservationConfig,
    SampleSource,
    SimulatedInterferometerSource,
)

BACKEND_RESULT_INTERVAL_S = 0.08


@dataclass
class BackendUpdate:
    """Reduced backend update sent from the worker process to the GUI."""

    result: CorrelatorResult | None
    status: dict[str, Any]


class CorrelatorBackendProcess:
    """Own a separate process for SDR streaming and FX correlation."""

    def __init__(self, config: ObservationConfig, source_mode: str) -> None:
        self.config = config
        self.source_mode = source_mode
        context = get_context("spawn")
        self._result_queue: Queue = context.Queue(maxsize=2)
        self._command_queue: Queue = context.Queue(maxsize=8)
        self._stop_event: Event = context.Event()
        self._process = context.Process(
            target=backend_worker,
            args=(
                config,
                source_mode,
                self._result_queue,
                self._command_queue,
                self._stop_event,
            ),
            name="RadioInterferometerBackend",
            daemon=True,
        )
        self._last_status: dict[str, Any] = {}

    def start(self) -> None:
        self._process.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._send_command({"type": "stop"})
        self._process.join(timeout=3.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2.0)

    def reset_average(self) -> None:
        self._send_command({"type": "reset_average"})

    def update_config(self, config: ObservationConfig, source_mode: str) -> None:
        self.config = config
        self.source_mode = source_mode
        self._send_command(
            {
                "type": "update_config",
                "config": config,
                "source_mode": source_mode,
            }
        )

    def poll_latest(self) -> BackendUpdate | None:
        latest: BackendUpdate | None = None
        while True:
            try:
                latest = self._result_queue.get_nowait()
            except Empty:
                break
        if latest is not None:
            self._last_status = latest.status
        return latest

    def status_snapshot(self) -> dict[str, Any]:
        return self._last_status

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def _send_command(self, command: dict[str, Any]) -> None:
        try:
            self._command_queue.put_nowait(command)
        except Full:
            try:
                self._command_queue.get_nowait()
            except Empty:
                pass
            self._command_queue.put_nowait(command)


def backend_worker(
    config: ObservationConfig,
    source_mode: str,
    result_queue: Queue,
    command_queue: Queue,
    stop_event: Event,
) -> None:
    source: SampleSource | None = None
    correlator: FXCorrelator | None = None
    overflow_count = 0
    processed_count = 0
    dropped_results = 0
    last_emit = 0.0

    try:
        source = make_source(config, source_mode)
        correlator = make_correlator(config)
        source.start()

        while not stop_event.is_set():
            config, source_mode, source, correlator = apply_pending_commands(
                command_queue,
                config,
                source_mode,
                source,
                correlator,
            )

            result: CorrelatorResult | None = None
            blocks_this_cycle = calculate_blocks_per_cycle(config, source_mode)
            for _ in range(blocks_this_cycle):
                if stop_event.is_set():
                    break
                try:
                    antenna_a, antenna_b = source.read(correlator.config.bins)
                except B210ReadOverflow:
                    overflow_count += 1
                    continue
                result = correlator.process(antenna_a, antenna_b)
                processed_count += 1

            now = monotonic()
            if result is not None and now - last_emit >= BACKEND_RESULT_INTERVAL_S:
                status = build_status(
                    source,
                    correlator,
                    processed_count,
                    overflow_count,
                    dropped_results,
                )
                dropped_results += put_latest_result(result_queue, BackendUpdate(result, status))
                last_emit = now
    except StopBackend:
        pass
    except Exception as exc:
        put_latest_result(
            result_queue,
            BackendUpdate(
                None,
                {
                    "error": str(exc),
                    "processed": processed_count,
                    "overflows": overflow_count,
                },
            ),
        )
    finally:
        if source is not None:
            try:
                source.stop()
            except Exception:
                pass


def apply_pending_commands(
    command_queue: Queue,
    config: ObservationConfig,
    source_mode: str,
    source: SampleSource,
    correlator: FXCorrelator,
) -> tuple[ObservationConfig, str, SampleSource, FXCorrelator]:
    while True:
        try:
            command = command_queue.get_nowait()
        except Empty:
            break

        command_type = command.get("type")
        if command_type == "stop":
            raise StopBackend
        if command_type == "reset_average":
            correlator.reset()
            continue
        if command_type != "update_config":
            continue

        new_config = command["config"]
        new_source_mode = command["source_mode"]
        if source_mode != new_source_mode or requires_source_restart(
            config, new_config, new_source_mode
        ):
            source.stop()
            source = make_source(new_config, new_source_mode)
            source.start()
        else:
            source.update_config(new_config)

        if requires_correlator_rebuild(config, new_config):
            correlator = make_correlator(new_config)
        config = new_config
        source_mode = new_source_mode

    return config, source_mode, source, correlator


class StopBackend(Exception):
    """Internal signal used to exit the backend worker."""


def make_source(config: ObservationConfig, source_mode: str) -> SampleSource:
    if source_mode == "B210 / SoapySDR":
        return B210SoapySource(config)
    return SimulatedInterferometerSource(config)


def make_correlator(config: ObservationConfig) -> FXCorrelator:
    return FXCorrelator(
        CorrelatorConfig(
            sample_rate_hz=config.sample_rate_hz,
            bins=config.bins,
            averaging_blocks=config.averaging_blocks,
        )
    )


def calculate_blocks_per_cycle(config: ObservationConfig, source_mode: str) -> int:
    if source_mode != "B210 / SoapySDR":
        return 1
    samples_per_update = config.sample_rate_hz * BACKEND_RESULT_INTERVAL_S
    blocks = ceil(samples_per_update / config.bins)
    return max(1, min(config.b210_process_blocks_per_update, blocks))


def build_status(
    source: SampleSource,
    correlator: FXCorrelator,
    processed_count: int,
    overflow_count: int,
    dropped_results: int,
) -> dict[str, Any]:
    status = source.status_snapshot()
    status.update(
        {
            "processed": processed_count,
            "overflows": status.get("overflows", 0) + overflow_count,
            "averaging_fill": correlator.averaging_fill_fraction,
            "dropped_results": dropped_results,
        }
    )
    return status


def put_latest_result(result_queue: Queue, update: BackendUpdate) -> int:
    dropped = 0
    while True:
        try:
            result_queue.put_nowait(update)
            return dropped
        except Full:
            try:
                result_queue.get_nowait()
                dropped += 1
            except Empty:
                return dropped


def requires_correlator_rebuild(old: ObservationConfig, new: ObservationConfig) -> bool:
    return (
        old.bandwidth_mhz != new.bandwidth_mhz
        or old.bins != new.bins
        or old.averaging_blocks != new.averaging_blocks
    )


def requires_source_restart(
    old: ObservationConfig,
    new: ObservationConfig,
    source_mode: str,
) -> bool:
    if source_mode != "B210 / SoapySDR":
        return False
    return (
        old.b210_device_args != new.b210_device_args
        or old.bandwidth_mhz != new.bandwidth_mhz
        or old.bins != new.bins
        or old.b210_stream_chunk_samples != new.b210_stream_chunk_samples
        or old.b210_queue_blocks != new.b210_queue_blocks
    )
