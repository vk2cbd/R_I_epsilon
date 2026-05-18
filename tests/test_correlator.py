import numpy as np

from radio_interferometer.correlator import (
    CorrelatorConfig,
    FXCorrelator,
    continuum_channel_mask,
    estimate_broadband_continuum_snr,
    estimate_peak_snr,
)


def test_fx_correlator_returns_requested_bin_count() -> None:
    bins = 128
    correlator = FXCorrelator(CorrelatorConfig(sample_rate_hz=1_000_000.0, bins=bins))
    indices = np.arange(bins)
    signal = np.exp(2j * np.pi * 0.125 * indices).astype(np.complex64)

    result = correlator.process(signal, signal)

    assert result.cross_spectrum.shape == (bins,)
    assert result.interferogram.shape == (bins,)
    assert result.frequency_offsets_hz.shape == (bins,)
    assert result.lag_bins[0] == -bins // 2
    assert result.lag_bins[-1] == bins // 2 - 1


def test_fx_correlator_pads_short_blocks() -> None:
    correlator = FXCorrelator(CorrelatorConfig(sample_rate_hz=2_000_000.0, bins=64))
    short_block = np.ones(16, dtype=np.complex64)

    result = correlator.process(short_block, short_block)

    assert result.cross_spectrum.shape == (64,)
    assert np.all(np.isfinite(result.cross_spectrum))


def test_fx_correlator_rejects_invalid_config() -> None:
    try:
        FXCorrelator(CorrelatorConfig(sample_rate_hz=0.0, bins=64))
    except ValueError as exc:
        assert "Sample rate" in str(exc)
    else:
        raise AssertionError("Expected invalid sample rate to raise ValueError")


def test_fx_correlator_uses_averaging_blocks_for_alpha() -> None:
    config = CorrelatorConfig(sample_rate_hz=1_000_000.0, bins=64, averaging_blocks=16)

    assert config.integration_alpha == 1.0 / 16.0


def test_estimate_peak_snr_excludes_peak_neighborhood() -> None:
    spectrum = np.ones(16)
    spectrum[8] = 10.0
    spectrum[7] = 4.0
    spectrum[9] = 5.0

    result = estimate_peak_snr(spectrum, exclusion_bins=1)

    assert result.index == 8
    assert result.peak_value == 10.0
    assert result.noise_floor == 1.0
    assert result.snr == 10.0


def test_continuum_channel_mask_excludes_edges_and_rfi() -> None:
    spectrum = np.ones(16, dtype=np.complex128)
    spectrum[8] = 100.0

    mask = continuum_channel_mask(spectrum, edge_percent=12.5, rfi_sigma=3.0)

    assert not np.any(mask[:2])
    assert not np.any(mask[-2:])
    assert not mask[8]
    assert np.count_nonzero(mask) == 11


def test_estimate_broadband_continuum_snr_uses_selected_bins() -> None:
    bins = 64
    offsets = np.fft.fftshift(np.fft.fftfreq(bins, d=1.0 / 1_000_000.0))
    cross = np.ones(bins, dtype=np.complex128)
    cross += 0.01 * np.exp(2j * np.pi * np.arange(bins) / bins)

    result = estimate_broadband_continuum_snr(
        cross,
        offsets,
        lag_bin=0.0,
        sample_rate_hz=1_000_000.0,
        edge_percent=10.0,
    )

    assert result.bins_used == 52
    assert result.amplitude > 0.9
    assert result.snr > 10.0
