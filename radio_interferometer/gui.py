"""Tkinter GUI for the radio interferometry FX correlator."""

from __future__ import annotations

import json
from math import ceil
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import __version__
from .correlator import (
    CorrelatorConfig,
    FXCorrelator,
    estimate_broadband_continuum_snr,
    estimate_peak_snr,
)
from .sources import (
    B210ReadOverflow,
    B210SoapySource,
    ObservationConfig,
    SampleSource,
    SimulatedInterferometerSource,
)

GUI_REFRESH_MS = 80
MAX_BLOCKS_PER_UPDATE = 2048
LIVE_APPLY_DELAY_MS = 800
SETTINGS_PATH = Path.home() / ".radio_interferometer_beta_settings.json"

FIELD_DEFAULTS = [
    ("observing_frequency_mhz", "Observing freq (MHz)", "4800.0"),
    ("intermediate_frequency_mhz", "B210 tune IF (MHz)", "1150.0"),
    ("ra_deg", "Source RA (deg)", "83.6331"),
    ("dec_deg", "Source DEC (deg)", "22.0145"),
    ("observer_lat_deg", "Observer lat (deg)", "-33.8688"),
    ("observer_lon_deg", "Observer lon (deg)", "151.2093"),
    ("bandwidth_mhz", "Bandwidth (MHz)", "30.72"),
    ("bins", "FX bins", "2048"),
    ("averaging_blocks", "X-corr smoothing blocks", "8196"),
    ("spectrum_smoothing_bins", "Spectrum smoothing bins", "1"),
    ("baseline_east_m", "Baseline east (m)", "6.0"),
    ("baseline_north_m", "Baseline north (m)", "0.0"),
    ("baseline_up_m", "Baseline up (m)", "0.0"),
    ("b210_gain_db", "B210 gain (dB)", "70.0"),
    ("b210_read_timeout_ms", "B210 read timeout (ms)", "1000"),
    ("b210_device_args", "B210 device args", "num_recv_frames=256"),
]

SCALE_FIELD_DEFAULTS = [
    ("interferogram_y_min", "Interferogram Y min", "0.0"),
    ("interferogram_y_max", "Interferogram Y max", "1.0"),
    ("spectrum_y_min", "Spectrum Y min", "0.0"),
    ("spectrum_y_max", "Spectrum Y max", "1.0"),
]

CONTINUUM_FIELD_DEFAULTS = [
    ("continuum_edge_percent", "Continuum edge exclude (%)", "10.0"),
    ("continuum_rfi_sigma", "Continuum RFI sigma (0 off)", "0.0"),
]

DEFAULT_SETTINGS = {
    "source_mode": "Simulator",
    "spectrum_plot_mode": "on",
    "phase_plot_mode": "off",
    "interferogram_autoscale": "on",
    "spectrum_autoscale": "on",
    "continuum_snr_mode": "on",
    **{key: default for key, _, default in FIELD_DEFAULTS},
    **{key: default for key, _, default in SCALE_FIELD_DEFAULTS},
    **{key: default for key, _, default in CONTINUUM_FIELD_DEFAULTS},
}


class InterferometryApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"Radio Interferometry FX Correlator v{__version__}")
        self.geometry("1180x780")
        self.minsize(980, 680)

        self._source: SampleSource | None = None
        self._correlator: FXCorrelator | None = None
        self._running = False
        self._latest_config: ObservationConfig | None = None
        self._latest_source_mode = "Simulator"
        self._blocks_per_update = 1
        self._overflow_count = 0
        self._runtime_apply_after_id: str | None = None
        self._loading_settings = True
        self._settings = load_settings()

        self._build_controls()
        self._build_plots()
        self._loading_settings = False
        self._save_settings()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_controls(self) -> None:
        controls = ttk.Frame(self)
        controls.pack(side=tk.LEFT, fill=tk.Y)
        controls_canvas = tk.Canvas(controls, width=320, highlightthickness=0)
        controls_scroll = ttk.Scrollbar(
            controls, orient=tk.VERTICAL, command=controls_canvas.yview
        )
        controls_canvas.configure(yscrollcommand=controls_scroll.set)
        controls_canvas.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        controls_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        panel = ttk.Frame(controls_canvas, padding=10)
        controls_window = controls_canvas.create_window((0, 0), window=panel, anchor="nw")

        def update_scroll_region(_event=None) -> None:
            controls_canvas.configure(scrollregion=controls_canvas.bbox("all"))
            controls_canvas.itemconfigure(controls_window, width=controls_canvas.winfo_width())

        panel.bind("<Configure>", update_scroll_region)
        controls_canvas.bind("<Configure>", update_scroll_region)

        self.source_mode = tk.StringVar(value=self._settings["source_mode"])
        ttk.Label(panel, text="Source").grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Combobox(
            panel,
            textvariable=self.source_mode,
            values=("Simulator", "B210 / SoapySDR"),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="ew", pady=(0, 8))

        self.spectrum_plot_mode = tk.StringVar(value=self._settings["spectrum_plot_mode"])
        self.phase_plot_mode = tk.StringVar(value=self._settings["phase_plot_mode"])
        ttk.Label(panel, text="Spectrum plot").grid(row=1, column=0, sticky="w", pady=3)
        spectrum_options = ttk.Frame(panel)
        spectrum_options.grid(row=1, column=1, sticky="w", pady=3)
        ttk.Radiobutton(
            spectrum_options,
            text="On",
            variable=self.spectrum_plot_mode,
            value="on",
            command=self._apply_plot_visibility,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            spectrum_options,
            text="Off",
            variable=self.spectrum_plot_mode,
            value="off",
            command=self._apply_plot_visibility,
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(panel, text="Phase plot").grid(row=2, column=0, sticky="w", pady=3)
        phase_options = ttk.Frame(panel)
        phase_options.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Radiobutton(
            phase_options,
            text="On",
            variable=self.phase_plot_mode,
            value="on",
            command=self._apply_plot_visibility,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            phase_options,
            text="Off",
            variable=self.phase_plot_mode,
            value="off",
            command=self._apply_plot_visibility,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.interferogram_autoscale = tk.StringVar(value=self._settings["interferogram_autoscale"])
        self.spectrum_autoscale = tk.StringVar(value=self._settings["spectrum_autoscale"])
        ttk.Label(panel, text="Interferogram scale").grid(row=3, column=0, sticky="w", pady=3)
        interferogram_scale_options = ttk.Frame(panel)
        interferogram_scale_options.grid(row=3, column=1, sticky="w", pady=3)
        ttk.Radiobutton(
            interferogram_scale_options,
            text="Auto",
            variable=self.interferogram_autoscale,
            value="on",
            command=self._apply_plot_scales,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            interferogram_scale_options,
            text="Manual",
            variable=self.interferogram_autoscale,
            value="off",
            command=self._apply_plot_scales,
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(panel, text="Spectrum scale").grid(row=4, column=0, sticky="w", pady=3)
        spectrum_scale_options = ttk.Frame(panel)
        spectrum_scale_options.grid(row=4, column=1, sticky="w", pady=3)
        ttk.Radiobutton(
            spectrum_scale_options,
            text="Auto",
            variable=self.spectrum_autoscale,
            value="on",
            command=self._apply_plot_scales,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            spectrum_scale_options,
            text="Manual",
            variable=self.spectrum_autoscale,
            value="off",
            command=self._apply_plot_scales,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.continuum_snr_mode = tk.StringVar(value=self._settings["continuum_snr_mode"])
        ttk.Label(panel, text="Continuum SNR").grid(row=5, column=0, sticky="w", pady=3)
        continuum_options = ttk.Frame(panel)
        continuum_options.grid(row=5, column=1, sticky="w", pady=3)
        ttk.Radiobutton(
            continuum_options,
            text="On",
            variable=self.continuum_snr_mode,
            value="on",
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            continuum_options,
            text="Off",
            variable=self.continuum_snr_mode,
            value="off",
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.inputs: dict[str, tk.StringVar] = {}
        for row, (key, label, default) in enumerate(FIELD_DEFAULTS, start=6):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=3)
            value = tk.StringVar(value=self._settings.get(key, default))
            self.inputs[key] = value
            ttk.Entry(panel, textvariable=value, width=18).grid(row=row, column=1, sticky="ew", pady=3)

        continuum_row = len(FIELD_DEFAULTS) + 6
        self.continuum_inputs: dict[str, tk.StringVar] = {}
        for row, (key, label, default) in enumerate(CONTINUUM_FIELD_DEFAULTS, start=continuum_row):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=3)
            value = tk.StringVar(value=self._settings.get(key, default))
            self.continuum_inputs[key] = value
            ttk.Entry(panel, textvariable=value, width=18).grid(row=row, column=1, sticky="ew", pady=3)

        scale_row = continuum_row + len(CONTINUUM_FIELD_DEFAULTS)
        self.scale_inputs: dict[str, tk.StringVar] = {}
        for row, (key, label, default) in enumerate(SCALE_FIELD_DEFAULTS, start=scale_row):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=3)
            value = tk.StringVar(value=self._settings.get(key, default))
            self.scale_inputs[key] = value
            ttk.Entry(panel, textvariable=value, width=18).grid(row=row, column=1, sticky="ew", pady=3)

        scale_button_row = scale_row + len(SCALE_FIELD_DEFAULTS)
        ttk.Button(panel, text="Apply Scales", command=self._apply_plot_scales).grid(
            row=scale_button_row, column=0, sticky="ew", pady=(8, 3)
        )
        ttk.Button(panel, text="Use Current Scales", command=self._capture_current_scales).grid(
            row=scale_button_row, column=1, sticky="ew", pady=(8, 3)
        )

        button_row = scale_button_row + 1
        self.start_button = ttk.Button(panel, text="Start", command=self.start)
        self.start_button.grid(row=button_row, column=0, sticky="ew", pady=(14, 3))
        self.stop_button = ttk.Button(panel, text="Stop", command=self.stop, state=tk.DISABLED)
        self.stop_button.grid(row=button_row, column=1, sticky="ew", pady=(14, 3))

        self.reset_button = ttk.Button(panel, text="Reset Avg", command=self.reset_average)
        self.reset_button.grid(row=button_row + 1, column=0, columnspan=2, sticky="ew", pady=3)

        ttk.Separator(panel).grid(row=button_row + 2, column=0, columnspan=2, sticky="ew", pady=12)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(panel, textvariable=self.status, wraplength=240).grid(
            row=button_row + 3, column=0, columnspan=2, sticky="w"
        )
        panel.columnconfigure(1, weight=1)

        self._watch_control(self.source_mode)
        self._watch_control(self.spectrum_plot_mode)
        self._watch_control(self.phase_plot_mode)
        self._watch_control(self.interferogram_autoscale)
        self._watch_control(self.spectrum_autoscale)
        self._watch_control(self.continuum_snr_mode)
        for value in self.inputs.values():
            self._watch_control(value)
        for value in self.continuum_inputs.values():
            self._watch_control(value)
        for value in self.scale_inputs.values():
            self._watch_control(value)

    def _build_plots(self) -> None:
        plot_frame = ttk.Frame(self, padding=(0, 10, 10, 10))
        plot_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.ax_interferogram = self.figure.add_subplot(211)
        self.ax_spectrum = self.figure.add_subplot(212)
        self.ax_phase = self.ax_spectrum.twinx()

        self.ax_interferogram.set_title("Realtime Interferogram")
        self.ax_interferogram.set_xlabel("Lag bin")
        self.ax_interferogram.set_ylabel("|Correlation|")
        self.ax_spectrum.set_title("Cross-Correlation Spectrum")
        self.ax_spectrum.set_xlabel("Sky frequency (MHz)")
        self.ax_spectrum.set_ylabel("|Cross power|")
        self.ax_phase.set_ylabel("Phase (rad)")

        (self.interferogram_line,) = self.ax_interferogram.plot([], [], color="#1f77b4", lw=1.4)
        (self.spectrum_line,) = self.ax_spectrum.plot(
            [], [], color="#2ca02c", lw=1.3, drawstyle="default"
        )
        (self.phase_line,) = self.ax_phase.plot([], [], color="#d62728", lw=1.0, alpha=0.78)
        self.peak_vline = self.ax_interferogram.axvline(
            0.0, color="#111111", lw=1.0, ls="--", alpha=0.7
        )
        (self.peak_marker,) = self.ax_interferogram.plot(
            [], [], marker="o", ms=6, color="#111111", linestyle="None"
        )
        self.snr_text = self.ax_interferogram.text(
            0.02,
            0.94,
            "Lag peak: --\nLag SNR: --\nContinuum SNR: --",
            transform=self.ax_interferogram.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.75},
        )

        self.figure.tight_layout()
        self._apply_plot_visibility(draw=False)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, plot_frame)

    def start(self) -> None:
        try:
            config = self._read_config()
            source = self._make_source(config)
            correlator = FXCorrelator(
                CorrelatorConfig(
                    sample_rate_hz=config.sample_rate_hz,
                    bins=config.bins,
                    averaging_blocks=config.averaging_blocks,
                )
            )
            source.start()
        except Exception as exc:
            messagebox.showerror("Unable to start", str(exc))
            self.status.set(f"Start failed: {exc}")
            return

        self._latest_config = config
        self._latest_source_mode = self.source_mode.get()
        self._source = source
        self._correlator = correlator
        self._blocks_per_update = self._calculate_blocks_per_update(config)
        self._overflow_count = 0
        self._running = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status.set(f"Running; X-corr smoothing {config.averaging_blocks} blocks")
        self.after(20, self._update_loop)

    def stop(self) -> None:
        self._running = False
        if self._source is not None:
            try:
                self._source.stop()
            except Exception as exc:
                self.status.set(f"Stopped with source warning: {exc}")
            else:
                self.status.set("Stopped")
        self._source = None
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def reset_average(self) -> None:
        if self._correlator is not None:
            self._correlator.reset()
            self.status.set("Averaging reset")

    def _update_loop(self) -> None:
        if not self._running or self._source is None or self._correlator is None:
            return

        try:
            if not self._apply_runtime_config_if_needed():
                self.after(GUI_REFRESH_MS, self._update_loop)
                return

            result = None
            processed = 0
            for _ in range(self._blocks_per_update):
                try:
                    antenna_a, antenna_b = self._source.read(self._correlator.config.bins)
                except B210ReadOverflow:
                    self._overflow_count += 1
                    continue
                result = self._correlator.process(antenna_a, antenna_b)
                processed += 1

            if result is not None:
                self._draw_result(result)

            if self._overflow_count:
                self.status.set(
                    f"Running; recovered {self._overflow_count} B210 overflow(s). "
                    f"Processed {processed}/{self._blocks_per_update} blocks."
                )
            else:
                self.status.set(f"Running; processed {processed} blocks/update")
        except Exception as exc:
            self.stop()
            messagebox.showerror("Runtime error", str(exc))
            return

        self.after(GUI_REFRESH_MS, self._update_loop)

    def _draw_result(self, result) -> None:
        config = self._latest_config
        if config is None:
            return

        sky_freq_mhz = config.observing_frequency_mhz + result.frequency_offsets_hz / 1_000_000.0
        interferogram_mag = np.abs(result.interferogram)
        spectrum_mag = np.abs(result.cross_spectrum)
        spectrum_envelope = smooth_line(spectrum_mag, config.spectrum_smoothing_bins)
        phase = np.angle(result.cross_spectrum)
        peak_snr = estimate_peak_snr(interferogram_mag)
        peak_lag_bin = float(result.lag_bins[peak_snr.index])
        continuum_text = "Continuum SNR: off"
        if self.continuum_snr_mode.get() == "on":
            try:
                continuum = estimate_broadband_continuum_snr(
                    result.cross_spectrum,
                    result.frequency_offsets_hz,
                    peak_lag_bin,
                    config.sample_rate_hz,
                    edge_percent=parse_float_var(
                        self.continuum_inputs["continuum_edge_percent"],
                        "Continuum edge exclude",
                    ),
                    rfi_sigma=parse_float_var(
                        self.continuum_inputs["continuum_rfi_sigma"],
                        "Continuum RFI sigma",
                    ),
                )
                continuum_text = (
                    f"Continuum SNR: {continuum.snr:.2f}\n"
                    f"Cont amp: {continuum.amplitude:.3g}\n"
                    f"Cont phase: {continuum.phase_rad:.3f} rad\n"
                    f"Clean bins: {continuum.bins_used}"
                )
            except ValueError as exc:
                continuum_text = f"Continuum SNR: {exc}"

        self.interferogram_line.set_data(result.lag_bins, interferogram_mag)
        self.peak_marker.set_data([peak_lag_bin], [peak_snr.peak_value])
        self.peak_vline.set_xdata([peak_lag_bin, peak_lag_bin])
        self.snr_text.set_text(
            f"Peak lag: {peak_lag_bin:.0f}\n"
            f"Lag SNR: {peak_snr.snr:.2f}\n"
            f"Lag noise: {peak_snr.noise_floor:.3g}\n"
            f"{continuum_text}"
        )
        self.ax_interferogram.set_xlim(float(result.lag_bins.min()), float(result.lag_bins.max()))
        if self.interferogram_autoscale.get() == "on":
            self.ax_interferogram.set_ylim(0, max(float(interferogram_mag.max()) * 1.15, 1e-6))

        self.spectrum_line.set_data(sky_freq_mhz, spectrum_envelope)
        self.phase_line.set_data(sky_freq_mhz, phase)
        self.ax_spectrum.set_xlim(float(sky_freq_mhz.min()), float(sky_freq_mhz.max()))
        if self.spectrum_autoscale.get() == "on":
            self.ax_spectrum.set_ylim(0, max(float(spectrum_envelope.max()) * 1.15, 1e-6))
        self.ax_phase.set_ylim(-np.pi, np.pi)
        self._apply_plot_visibility(draw=False)
        self._apply_plot_scales(draw=False)

        self.canvas.draw_idle()

    def _read_config(self) -> ObservationConfig:
        values: dict[str, float | int | str] = {}
        for key, var in self.inputs.items():
            raw = var.get().strip()
            if key == "b210_device_args":
                values[key] = raw
            elif key in {
                "bins",
                "averaging_blocks",
                "spectrum_smoothing_bins",
                "b210_read_timeout_ms",
            }:
                values[key] = int(raw)
            else:
                values[key] = float(raw)

        if values["bandwidth_mhz"] <= 0:
            raise ValueError("Bandwidth must be positive.")
        if values["bins"] < 8:
            raise ValueError("FX bins must be at least 8.")
        if values["bins"] & (values["bins"] - 1):
            raise ValueError("FX bins should be a power of two for realtime FFT performance.")
        if values["averaging_blocks"] < 1:
            raise ValueError("Averaging blocks must be at least 1.")
        if values["spectrum_smoothing_bins"] < 1:
            raise ValueError("Spectrum smoothing bins must be at least 1.")
        if not -90 <= values["observer_lat_deg"] <= 90:
            raise ValueError("Observer latitude must be between -90 and 90 degrees.")
        if not -90 <= values["dec_deg"] <= 90:
            raise ValueError("Source DEC must be between -90 and 90 degrees.")
        if values["b210_read_timeout_ms"] < 100:
            raise ValueError("B210 read timeout must be at least 100 ms.")
        if values["b210_gain_db"] < 0:
            raise ValueError("B210 gain must not be negative.")

        return ObservationConfig(**values)

    def _make_source(self, config: ObservationConfig) -> SampleSource:
        if self.source_mode.get() == "B210 / SoapySDR":
            return B210SoapySource(config)
        return SimulatedInterferometerSource(config)

    def _calculate_blocks_per_update(self, config: ObservationConfig) -> int:
        if self.source_mode.get() != "B210 / SoapySDR":
            return 1

        samples_per_update = config.sample_rate_hz * (GUI_REFRESH_MS / 1000.0)
        blocks = ceil(samples_per_update / config.bins)
        return max(1, min(MAX_BLOCKS_PER_UPDATE, blocks))

    def _watch_control(self, value: tk.StringVar) -> None:
        value.trace_add("write", lambda *_args: self._on_control_changed())

    def _on_control_changed(self) -> None:
        if self._loading_settings:
            return
        self._save_settings()
        self._apply_plot_visibility(draw=False)
        self._apply_plot_scales(draw=False)
        if self._running:
            self._schedule_runtime_apply()

    def _schedule_runtime_apply(self) -> None:
        if self._runtime_apply_after_id is not None:
            self.after_cancel(self._runtime_apply_after_id)
        self._runtime_apply_after_id = self.after(
            LIVE_APPLY_DELAY_MS, self._run_scheduled_runtime_apply
        )

    def _run_scheduled_runtime_apply(self) -> None:
        self._runtime_apply_after_id = None
        if self._running:
            self._apply_runtime_config_if_needed()

    def _apply_runtime_config_if_needed(self) -> bool:
        if self._source is None or self._correlator is None or self._latest_config is None:
            return True

        try:
            config = self._read_config()
        except Exception as exc:
            self.status.set(f"Live settings not applied yet: {exc}")
            return False

        source_mode = self.source_mode.get()
        if config == self._latest_config and source_mode == self._latest_source_mode:
            return True

        if source_mode != self._latest_source_mode or requires_source_restart(
            self._latest_config, config
        ):
            try:
                self._replace_running_source(config)
            except Exception as exc:
                self.stop()
                messagebox.showerror("Runtime reconfiguration failed", str(exc))
                return False
        else:
            try:
                self._source.update_config(config)
            except Exception as exc:
                self.stop()
                messagebox.showerror("Runtime reconfiguration failed", str(exc))
                return False

        if requires_correlator_rebuild(self._latest_config, config):
            self._correlator = FXCorrelator(
                CorrelatorConfig(
                    sample_rate_hz=config.sample_rate_hz,
                    bins=config.bins,
                    averaging_blocks=config.averaging_blocks,
                )
            )

        self._latest_config = config
        self._latest_source_mode = source_mode
        self._blocks_per_update = self._calculate_blocks_per_update(config)
        self.status.set(f"Live settings applied; X-corr smoothing {config.averaging_blocks} blocks")
        return True

    def _replace_running_source(self, config: ObservationConfig) -> None:
        old_source = self._source
        if old_source is not None:
            old_source.stop()

        new_source = self._make_source(config)
        new_source.start()
        self._source = new_source
        self._overflow_count = 0

    def _apply_plot_visibility(self, draw: bool = True) -> None:
        spectrum_enabled = self.spectrum_plot_mode.get() == "on"
        phase_enabled = self.phase_plot_mode.get() == "on"
        self.spectrum_line.set_visible(spectrum_enabled)
        self.phase_line.set_visible(phase_enabled)
        self.ax_phase.set_visible(phase_enabled)
        if draw:
            self.canvas.draw_idle()

    def _apply_plot_scales(self, draw: bool = True) -> None:
        try:
            if self.interferogram_autoscale.get() == "off":
                y_min = parse_scale_value(self.scale_inputs["interferogram_y_min"])
                y_max = parse_scale_value(self.scale_inputs["interferogram_y_max"])
                validate_scale_limits(y_min, y_max)
                self.ax_interferogram.set_ylim(
                    y_min,
                    y_max,
                )
            if self.spectrum_autoscale.get() == "off":
                y_min = parse_scale_value(self.scale_inputs["spectrum_y_min"])
                y_max = parse_scale_value(self.scale_inputs["spectrum_y_max"])
                validate_scale_limits(y_min, y_max)
                self.ax_spectrum.set_ylim(
                    y_min,
                    y_max,
                )
        except ValueError as exc:
            self.status.set(f"Plot scale not applied: {exc}")
            return
        if draw:
            self.canvas.draw_idle()

    def _capture_current_scales(self) -> None:
        interferogram_min, interferogram_max = self.ax_interferogram.get_ylim()
        spectrum_min, spectrum_max = self.ax_spectrum.get_ylim()
        self.scale_inputs["interferogram_y_min"].set(f"{interferogram_min:.6g}")
        self.scale_inputs["interferogram_y_max"].set(f"{interferogram_max:.6g}")
        self.scale_inputs["spectrum_y_min"].set(f"{spectrum_min:.6g}")
        self.scale_inputs["spectrum_y_max"].set(f"{spectrum_max:.6g}")
        self._apply_plot_scales()

    def _save_settings(self) -> None:
        settings = {
            "source_mode": self.source_mode.get(),
            "spectrum_plot_mode": self.spectrum_plot_mode.get(),
            "phase_plot_mode": self.phase_plot_mode.get(),
            "interferogram_autoscale": self.interferogram_autoscale.get(),
            "spectrum_autoscale": self.spectrum_autoscale.get(),
            "continuum_snr_mode": self.continuum_snr_mode.get(),
        }
        settings.update({key: value.get() for key, value in self.inputs.items()})
        settings.update({key: value.get() for key, value in self.continuum_inputs.items()})
        settings.update({key: value.get() for key, value in self.scale_inputs.items()})
        try:
            SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError as exc:
            self.status.set(f"Settings not saved: {exc}")

    def _close(self) -> None:
        self._save_settings()
        self.stop()
        self.destroy()


def smooth_line(values: np.ndarray, bins: int) -> np.ndarray:
    """Return a moving-average envelope for a plotted spectrum line."""

    if bins <= 1 or values.size < 2:
        return values
    width = min(int(bins), values.size)
    kernel = np.ones(width, dtype=np.float64) / width
    return np.convolve(values, kernel, mode="same")


def parse_scale_value(value: tk.StringVar) -> float:
    parsed = float(value.get().strip())
    if not np.isfinite(parsed):
        raise ValueError("Scale limits must be finite numbers.")
    return parsed


def parse_float_var(value: tk.StringVar, label: str) -> float:
    try:
        parsed = float(value.get().strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be numeric.") from exc
    if not np.isfinite(parsed):
        raise ValueError(f"{label} must be finite.")
    return parsed


def validate_scale_limits(y_min: float, y_max: float) -> None:
    if y_min >= y_max:
        raise ValueError("Manual scale minimum must be less than maximum.")


def requires_correlator_rebuild(old: ObservationConfig, new: ObservationConfig) -> bool:
    return (
        old.bandwidth_mhz != new.bandwidth_mhz
        or old.bins != new.bins
        or old.averaging_blocks != new.averaging_blocks
    )


def requires_source_restart(old: ObservationConfig, new: ObservationConfig) -> bool:
    return old.b210_device_args != new.b210_device_args


def load_settings() -> dict[str, str]:
    settings = DEFAULT_SETTINGS.copy()
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if isinstance(loaded, dict):
        for key, value in loaded.items():
            if key in settings:
                settings[key] = str(value)
    if settings["source_mode"] not in {"Simulator", "B210 / SoapySDR"}:
        settings["source_mode"] = DEFAULT_SETTINGS["source_mode"]
    for key in (
        "spectrum_plot_mode",
        "phase_plot_mode",
        "interferogram_autoscale",
        "spectrum_autoscale",
        "continuum_snr_mode",
    ):
        if settings[key] not in {"on", "off"}:
            settings[key] = DEFAULT_SETTINGS[key]
    return settings


def main() -> None:
    app = InterferometryApp()
    app.mainloop()
