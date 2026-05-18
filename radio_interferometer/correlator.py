"""FX correlator primitives."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CorrelatorConfig:
    """Runtime configuration for the FX correlator."""

    sample_rate_hz: float
    bins: int
    averaging_blocks: int = 32

    @property
    def integration_alpha(self) -> float:
        return 1.0 / self.averaging_blocks


@dataclass
class CorrelatorResult:
    """A single integrated correlator update."""

    frequency_offsets_hz: np.ndarray
    cross_spectrum: np.ndarray
    interferogram: np.ndarray
    lag_bins: np.ndarray


@dataclass(frozen=True)
class PeakSnr:
    """Peak and signal-to-noise estimate for a magnitude spectrum."""

    index: int
    peak_value: float
    noise_floor: float
    snr: float


@dataclass(frozen=True)
class BroadbandContinuumSnr:
    """Coherent wideband visibility and SNR estimate."""

    visibility: complex
    amplitude: float
    phase_rad: float
    noise_floor: float
    snr: float
    bins_used: int
    lag_bin: float
    edge_bins_excluded: int


class FXCorrelator:
    """Two-input FX correlator with exponential integration."""

    def __init__(self, config: CorrelatorConfig) -> None:
        if config.bins < 8:
            raise ValueError("FX bin count must be at least 8.")
        if config.sample_rate_hz <= 0:
            raise ValueError("Sample rate must be positive.")
        if config.averaging_blocks < 1:
            raise ValueError("Averaging blocks must be at least 1.")

        self.config = config
        self._window = np.hanning(config.bins).astype(np.float64)
        self._window_power = np.sum(self._window**2)
        self._integrated_cross: np.ndarray | None = None
        self.frequency_offsets_hz = np.fft.fftshift(
            np.fft.fftfreq(config.bins, d=1.0 / config.sample_rate_hz)
        )
        self.lag_bins = np.arange(-config.bins // 2, config.bins // 2)
        self._processed_blocks = 0

    def reset(self) -> None:
        self._integrated_cross = None
        self._processed_blocks = 0

    @property
    def averaging_fill_fraction(self) -> float:
        return min(1.0, self._processed_blocks / self.config.averaging_blocks)

    def process(self, antenna_a: np.ndarray, antenna_b: np.ndarray) -> CorrelatorResult:
        """Correlate two complex sample blocks and return integrated products."""

        count = self.config.bins
        a = self._prepare_block(antenna_a, count)
        b = self._prepare_block(antenna_b, count)

        spectrum_a = np.fft.fft(a * self._window)
        spectrum_b = np.fft.fft(b * self._window)
        cross = spectrum_a * np.conj(spectrum_b) / self._window_power

        if self._integrated_cross is None:
            self._integrated_cross = cross
        else:
            alpha = self.config.integration_alpha
            self._integrated_cross = (1.0 - alpha) * self._integrated_cross + alpha * cross
        self._processed_blocks += 1

        shifted_cross = np.fft.fftshift(self._integrated_cross)
        interferogram = np.fft.fftshift(np.fft.ifft(self._integrated_cross))

        return CorrelatorResult(
            frequency_offsets_hz=self.frequency_offsets_hz.copy(),
            cross_spectrum=shifted_cross.copy(),
            interferogram=interferogram,
            lag_bins=self.lag_bins.copy(),
        )

    @staticmethod
    def _prepare_block(samples: np.ndarray, count: int) -> np.ndarray:
        data = np.asarray(samples, dtype=np.complex64)
        if data.size < count:
            padded = np.zeros(count, dtype=np.complex64)
            padded[: data.size] = data
            return padded
        return data[:count]


def estimate_peak_snr(magnitudes: np.ndarray, exclusion_bins: int = 3) -> PeakSnr:
    """Find the strongest bin and estimate SNR against the surrounding noise floor."""

    values = np.asarray(magnitudes, dtype=np.float64)
    if values.size == 0:
        raise ValueError("Cannot estimate SNR from an empty spectrum.")
    if exclusion_bins < 0:
        raise ValueError("Exclusion bins must not be negative.")

    peak_index = int(np.nanargmax(values))
    peak_value = float(values[peak_index])

    mask = np.ones(values.size, dtype=bool)
    start = max(0, peak_index - exclusion_bins)
    stop = min(values.size, peak_index + exclusion_bins + 1)
    mask[start:stop] = False
    noise_values = values[mask]
    if noise_values.size == 0:
        noise_values = values

    noise_floor = float(np.nanmedian(noise_values))
    if not np.isfinite(noise_floor) or noise_floor <= 0.0:
        noise_floor = float(np.nanmean(noise_values))
    if not np.isfinite(noise_floor) or noise_floor <= 0.0:
        noise_floor = 1e-12

    return PeakSnr(
        index=peak_index,
        peak_value=peak_value,
        noise_floor=noise_floor,
        snr=peak_value / noise_floor,
    )


def estimate_broadband_continuum_snr(
    cross_spectrum: np.ndarray,
    frequency_offsets_hz: np.ndarray,
    lag_bin: float,
    sample_rate_hz: float,
    edge_percent: float = 10.0,
    rfi_sigma: float = 0.0,
) -> BroadbandContinuumSnr:
    """Estimate continuum SNR by coherently summing clean, phase-aligned channels."""

    cross = np.asarray(cross_spectrum, dtype=np.complex128)
    offsets = np.asarray(frequency_offsets_hz, dtype=np.float64)
    if cross.size == 0:
        raise ValueError("Cannot estimate continuum SNR from an empty spectrum.")
    if cross.shape != offsets.shape:
        raise ValueError("Cross spectrum and frequency offsets must have matching shapes.")
    if sample_rate_hz <= 0:
        raise ValueError("Sample rate must be positive.")
    if edge_percent < 0 or edge_percent >= 50:
        raise ValueError("Continuum edge exclusion must be in the range 0 to <50 percent.")
    if rfi_sigma < 0:
        raise ValueError("RFI sigma threshold must not be negative.")

    mask = continuum_channel_mask(cross, edge_percent=edge_percent, rfi_sigma=rfi_sigma)
    bins_used = int(np.count_nonzero(mask))
    if bins_used < 1:
        raise ValueError("Continuum channel mask removed all frequency bins.")

    delay_s = lag_bin / sample_rate_hz
    phasor = np.exp(2j * np.pi * offsets * delay_s)
    visibility = complex(np.mean(cross[mask] * phasor[mask]))
    amplitude = float(abs(visibility))

    lag_profile = np.fft.fftshift(np.fft.ifft(np.fft.ifftshift(np.where(mask, cross, 0.0))))
    lag_magnitudes = np.abs(lag_profile)
    noise_floor = estimate_lag_noise_floor(lag_magnitudes * cross.size / bins_used, lag_bin)

    return BroadbandContinuumSnr(
        visibility=visibility,
        amplitude=amplitude,
        phase_rad=float(np.angle(visibility)),
        noise_floor=noise_floor,
        snr=amplitude / noise_floor,
        bins_used=bins_used,
        lag_bin=float(lag_bin),
        edge_bins_excluded=int((cross.size - np.count_nonzero(edge_mask(cross.size, edge_percent))) // 2),
    )


def continuum_channel_mask(
    cross_spectrum: np.ndarray,
    edge_percent: float = 10.0,
    rfi_sigma: float = 0.0,
) -> np.ndarray:
    """Return a mask selecting interior channels and optionally rejecting RFI outliers."""

    cross = np.asarray(cross_spectrum)
    mask = edge_mask(cross.size, edge_percent)
    if rfi_sigma <= 0 or np.count_nonzero(mask) < 4:
        return mask

    magnitudes = np.abs(cross)
    selected = magnitudes[mask]
    median = float(np.nanmedian(selected))
    mad = float(np.nanmedian(np.abs(selected - median)))
    if not np.isfinite(mad) or mad <= 0.0:
        mask &= magnitudes <= median
        return mask

    robust_sigma = 1.4826 * mad
    threshold = median + rfi_sigma * robust_sigma
    mask &= magnitudes <= threshold
    return mask


def edge_mask(size: int, edge_percent: float) -> np.ndarray:
    """Mask out a percentage of bins from each band edge."""

    if size < 1:
        return np.zeros(0, dtype=bool)
    edge_bins = int(size * edge_percent / 100.0)
    edge_bins = min(edge_bins, max(0, (size - 1) // 2))
    mask = np.ones(size, dtype=bool)
    if edge_bins:
        mask[:edge_bins] = False
        mask[-edge_bins:] = False
    return mask


def estimate_lag_noise_floor(lag_magnitudes: np.ndarray, lag_bin: float, exclusion_bins: int = 3) -> float:
    """Estimate off-peak delay-domain noise around a possibly fractional lag."""

    values = np.asarray(lag_magnitudes, dtype=np.float64)
    if values.size == 0:
        return 1e-12

    center_index = int(round(lag_bin + values.size // 2))
    center_index = max(0, min(values.size - 1, center_index))
    mask = np.ones(values.size, dtype=bool)
    start = max(0, center_index - exclusion_bins)
    stop = min(values.size, center_index + exclusion_bins + 1)
    mask[start:stop] = False
    noise_values = values[mask]
    if noise_values.size == 0:
        noise_values = values

    noise_floor = float(np.nanmedian(noise_values))
    if not np.isfinite(noise_floor) or noise_floor <= 0.0:
        noise_floor = float(np.nanmean(noise_values))
    if not np.isfinite(noise_floor) or noise_floor <= 0.0:
        noise_floor = 1e-12
    return noise_floor
