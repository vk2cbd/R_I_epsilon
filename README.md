# Radio Interferometry FX Correlator

Initial Python 3 application for a two-input radio interferometer using an FX
correlator. The program provides a Tkinter GUI for observing parameters and
shows live plots for:

- Lag-domain interferogram from the inverse FFT of the cross spectrum.
- Cross-correlation spectrum amplitude and phase.

The current build includes a deterministic simulated two-antenna source so the
GUI and correlator can be tested without hardware. A B210 source adapter is
included as a starting point for UHD/SoapySDR integration.

## Ubuntu Setup

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

For development checks:

```bash
pip install -e ".[dev]"
pytest
```

For an Ettus B210 hardware path, install the UHD/SoapySDR stack for your Ubuntu
release and make sure the B210 is visible before selecting `B210 / SoapySDR` in
the GUI.

Useful B210 checks before starting the GUI:

```bash
uhd_find_devices
uhd_usrp_probe
SoapySDRUtil --find
```

If B210 startup reports a UHD control timeout such as
`accum_timeout < _timeout in wait_for_ack`, first try:

- Connect the B210 directly to a USB 3 port, not through a hub.
- Close any other program using the B210.
- Start with a low bandwidth such as `1.0` or `2.0` MHz.
- Use larger FX bins if overflows continue, for example `4096` or `8192`.
- Use manual B210 gain in the GUI, for example `35` dB.
- If more than one SDR is connected, set `B210 device args` to the serial, for
  example `serial=XXXXXXXX`.

## Version Control

This directory is a Git repository. The first version is intended as a retained
baseline for future changes and should be pushed to `vk2cbd/test` on GitHub.

## Current Inputs

- Observing frequency in MHz.
- Intermediate frequency in MHz, used as the SDR tune frequency for hardware.
- Source RA and DEC in decimal degrees.
- Observer latitude and longitude in decimal degrees.
- Bandwidth in MHz.
- Number of FX frequency bins.
- Cross-correlation smoothing blocks for reducing noise in the correlation plot.
- Spectrum and phase plot visibility controls. Spectrum is on by default; phase
  is off by default.
- Spectrum smoothing bins for the plotted spectrum envelope line.
- Live parameter updates while the app is running. Stream and correlator
  settings are re-applied after valid edits.
- Saved GUI settings are restored the next time the app starts.
- Auto/manual Y-axis scaling controls for the interferogram and spectrum plots.
- Realtime strongest-lag marker and SNR estimate on the interferogram plot.
- Broadband continuum SNR mode with edge-channel exclusion and optional
  RFI-outlier rejection before coherent frequency-bin summing.
- Continuous B210 streaming with a background reader thread and bounded queue,
  so plotting and FFT work do not directly interrupt SDR reads.
- Configurable B210 stream chunk samples so hardware `readStream()` transfers
  can be larger than the FX block size.
- Baseline east/north/up in meters for geometric phase simulation.
- B210 manual gain, read timeout, and optional SoapySDR device args.

## Notes

The correlator currently expects two complex streams with matching sample rate.
The simulator generates a narrowband source plus noise and applies a geometric
delay based on the source and observer coordinates. The hardware adapter is
kept intentionally small so later work can choose the preferred B210 driver
stack and buffering strategy.
