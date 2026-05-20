# Radio Interferometry App: One-Page User Guide

This app compares two receiver inputs from either the built-in simulator or an Ettus B210 SDR. It calculates the complex correlation between the two inputs and displays three main observing products: a lag-domain interferogram, a cross-correlation spectrum, and phase. It can also display and record a broadband visibility value for later analysis.

## Starting the App

On Ubuntu, install Python, Tkinter, UHD/SoapySDR if using the B210, then run:

```bash
python3 main.py
```

Choose `Simulator` for software testing or `B210 / SoapySDR` for hardware. For B210 use, check that `uhd_find_devices`, `uhd_usrp_probe`, and `SoapySDRUtil --find` can see the device before starting.

## Important GUI Fields

`Observing freq (MHz)` is the sky/RF frequency used for phase and visibility interpretation. `B210 tune IF (MHz)` is the frequency the SDR is tuned to. `Source RA/DEC` and `Observer lat/lon` describe the target and observing site. `Bandwidth (MHz)` sets the SDR sample rate and displayed frequency span. `FX bins` sets the number of frequency channels. More bins give finer frequency resolution but more CPU load.

`X-corr smoothing blocks` controls time integration of the complex visibility. Larger values reduce noise, but if the fringe phase changes during the integration, too much smoothing can reduce or smear the fringe. `Spectrum smoothing bins` smooths the displayed spectrum envelope only.

`Baseline east/north/up` describes antenna separation for simulation and future geometric delay work. `B210 gain`, `B210 read timeout`, `B210 stream chunk samples`, `B210 queued FFT blocks`, `B210 FFT blocks/update`, and `B210 device args` control hardware acquisition and buffering. The default device args include `num_recv_frames=256`.

Text fields apply only after pressing Enter in a field. Radio buttons apply immediately.

## Plots and Readouts

The top plot is the realtime interferogram. The strongest lag peak is marked and reported with lag SNR. The lower plot shows cross-correlation spectrum amplitude; phase can be turned on or off. Autoscale can be enabled or manual Y-axis limits can be used.

The broadband visibility readout shows one integrated continuum value: real part, imaginary part, amplitude, phase, and SNR. This is usually more useful for weak continuum sources than looking at noisy per-bin phase alone.

## Recording Visibilities

Set `Record visibilities` to `On`, choose `Visibility CSV path`, and set `Visibility record interval (s)`. A value of `1.0` records about once per second. A value of `0` records every backend update. The file is CSV format with a header row and one row per recorded broadband visibility sample. It records integrated visibility, not raw SDR data.

## Getting Good Results

Start in simulator mode to verify the GUI. With the B210, begin with modest bandwidth if streaming is unstable, then increase bandwidth. Use enough `X-corr smoothing blocks` to reduce noise, but avoid values so large that fringe motion is averaged away. For weak sources, trust integrated broadband visibility more than individual noisy phase bins. If `overflows` rise or the B210 LEDs indicate unstable streaming, reduce bandwidth, reduce processing load, increase FFT bins, or revisit hardware USB connection and UHD/SoapySDR setup.

The current safe development base is the process-isolated Delta visibility-recording version. Do not use the deleted Epsilon GUI-refresh-control experiment as a base because it caused Linux machine crashes during testing.
