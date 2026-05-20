# Radio Interferometry App: Architecture Overview

This application is a Python 3 radio-interferometry prototype for two coherent receiver channels, currently aimed at an Ettus B210 SDR or a built-in simulator. It measures how similar the two received signals are as a function of frequency and delay. That similarity is called the complex cross-correlation or visibility. The app is intended as a development platform rather than a finished observatory package.

## High-Level Architecture

The program starts from `main.py`, which launches the Tkinter GUI in `radio_interferometer/gui.py`. The GUI collects observation settings, displays plots, shows status, and optionally records broadband visibility values to CSV. To reduce the chance that plotting interrupts SDR streaming, the actual sample handling runs in a separate backend process implemented in `radio_interferometer/backend.py`.

The backend owns the selected sample source. In simulator mode it uses `SimulatedInterferometerSource`; in hardware mode it uses `B210SoapySource`, both defined in `radio_interferometer/sources.py`. The B210 path uses SoapySDR/UHD to configure two RX channels, set sample rate, RF bandwidth, IF tune frequency, manual gain, and device arguments. It then starts a time-aligned two-channel RX stream and continuously reads complex samples.

## Data Flow

The source produces two complex sample streams, one for each antenna/input. The backend passes matching blocks of samples into the FX correlator in `radio_interferometer/correlator.py`. "F" means each block is Fourier transformed into frequency bins. "X" means the app multiplies one spectrum by the complex conjugate of the other:

`cross_spectrum = FFT(A) * conj(FFT(B))`

This complex cross-spectrum is integrated over time using the GUI field `X-corr smoothing blocks`. The integrated result is sent to the GUI as reduced data: cross-correlation spectrum, phase, and lag-domain interferogram. The GUI does not receive or plot raw SDR sample streams.

The interferogram is produced by inverse FFT of the integrated cross-spectrum. A peak marker identifies the strongest lag bin and estimates a basic lag SNR. Broadband continuum visibility is calculated by selecting clean frequency bins, phase-aligning them to the detected lag, and averaging them into one complex value with real, imaginary, amplitude, phase, and SNR readouts.

## GUI and Runtime Control

Most text-entry parameters are committed only when the user presses Enter. This prevents half-typed values from being applied while the app is running. Plot visibility, autoscale controls, continuum SNR on/off, and visibility recording on/off use radio buttons. Settings are saved in the user home directory and restored at startup.

The GUI can record broadband visibilities to a CSV file. It writes integrated, reduced visibility rows rather than raw samples. The output includes timestamp, observing setup, baseline, source/observer coordinates, lag bin, complex visibility, amplitude, phase, SNR, noise floor, and clean-bin count.

## Issues Addressed

Earlier versions read and processed samples directly in the GUI loop, which could make B210 streaming intermittent. Later versions added background streaming, larger hardware reads, and bounded queues. The current safe architecture separates GUI and backend processes so plotting load is less likely to interrupt sample handling. A later experiment that removed bounded dropping caused machine instability and must not be used as a development base.

## Future Development

Likely next steps are better phase handling, delay-slope fitting/removal, richer visibility recording formats such as HDF5 or UVFITS-like structures, calibration tools, source tracking/fringe rotation, more robust B210 diagnostics, and eventually a lower-level C++/GNU Radio streaming backend if full-rate continuous acquisition remains beyond Python's reliable limits.
