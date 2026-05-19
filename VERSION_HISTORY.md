# Version History

## 0.3.1-delta - Broadband Visibility Display and Recording

- Added realtime broadband visibility readout with real, imaginary, amplitude,
  phase, and SNR values.
- Added visibility recording controls for on/off, CSV output path, and recording
  interval.
- CSV visibility recording writes integrated broadband continuum visibility rows
  for post-processing.

## 0.3.0-delta - Process-Isolated Correlator Backend

- Moved SDR streaming, sample reading, FFT correlation, and averaging into a
  separate backend process.
- Changed the Tkinter GUI to receive reduced correlator products instead of
  reading raw B210 sample blocks directly.
- Added a bounded result queue so stale plot updates are dropped before they can
  slow down the streaming/correlation backend.
- Kept committed text-entry behavior: text fields apply only after Enter.
- Changed persisted settings to a Delta-specific settings file.

## 0.2.4-beta - Committed Inputs and Averaging Draw Throttle

- Text-entry GUI parameters now commit only when the user presses Enter in an
  entry field; partially typed values are no longer applied while running.
- Runtime config, continuum settings, scale settings, and saved settings now use
  the last committed text-entry values.
- Reduced B210 plot redraw rate while the cross-correlation average is refilling
  so GUI drawing is less likely to interrupt continuous hardware streaming.
- Added averaging fill percentage to the runtime status line.

## 0.2.3-beta - B210 Stream-First Backpressure

- Prioritized continuous B210 draining by dropping excess FFT blocks before
  they create Python copy and FFT backlog.
- Added bounded B210 queue controls so realtime display work cannot grow until
  it starves the hardware read thread.
- Increased default B210 hardware read chunk size to `262144` samples.
- Added `B210 queued FFT blocks` and `B210 FFT blocks/update` GUI fields.

## 0.2.2-beta - Large-Chunk B210 Streaming

- Changed the B210 reader thread to request larger continuous `readStream()`
  transfers instead of one hardware read per FFT block.
- Split each returned B210 chunk into FX-sized blocks inside the app so the
  correlator pipeline still receives normal block sizes.
- Added a `B210 stream chunk samples` GUI field, defaulting to `65536`, for
  tuning hardware read cadence independently of FX bin count.
- Restart B210 streaming cleanly when the live stream chunk size changes.

## 0.2.1-beta - Continuous B210 Streaming

- Added a dedicated B210 stream reader thread that continuously drains
  `readStream()` into a bounded block queue.
- Changed GUI/correlator processing to consume queued B210 blocks instead of
  directly pacing hardware reads from the GUI update loop.
- Added B210 queue, dropped-block, overflow, and timeout counters to runtime
  status output.
- Restart B210 streaming cleanly when live bandwidth, bin count, or device args
  change.

## 0.2.0-beta - Broadband Continuum SNR

- Branched from the alpha interferometer app for beta development.
- Added broadband continuum SNR mode that phase-aligns and coherently averages
  selected cross-spectrum bins at the detected lag.
- Added edge-channel exclusion and optional RFI outlier rejection for continuum
  bin selection.
- Added continuum visibility amplitude, phase, SNR, and clean-bin count readout.

## 0.1.8-dev - Interferogram Peak Marker and SNR

- Branched from the frozen `v0.1.7` baseline.
- Added a realtime peak marker on the interferogram.
- Added a realtime SNR estimate using the strongest lag bin and the median
  non-peak interferogram level.
- Added spectrum and phase plot radio-button visibility controls, with spectrum
  on and phase off by default.
- Added spectrum smoothing bins for the displayed spectrum envelope line.
- Added live GUI parameter updates while the app is running.
- Added persisted GUI settings loaded at startup.
- Added auto/manual Y-axis scale controls for the interferogram and spectrum
  plots.
- Updated default bandwidth to 30.72 MHz, FX bins to 2048, smoothing to 8196
  blocks, B210 gain to 70 dB, and B210 device args to `num_recv_frames=256`.

## 0.1.7 - Clear Cross-Correlation Smoothing Control

- Renamed the averaging GUI field to `X-corr smoothing blocks`.
- Show the active smoothing block count in the run status.

## 0.1.6 - GUI Averaging Control

- Added an averaging blocks GUI parameter for reducing correlation plot noise.
- Use the averaging value to set the FX correlator integration length.

## 0.1.5 - Updated 4800 MHz Default

- Set the default observing frequency to 4800 MHz.
- Kept the default B210 IF tune frequency at 1150 MHz.
- Kept the default east baseline at 6 m.

## 0.1.4 - Updated Observing Defaults

- Set the default observing frequency to 8500 MHz.
- Set the default B210 IF tune frequency to 1150 MHz.
- Set the default east baseline to 6 m.

## 0.1.3 - B210 Overflow Recovery

- Drain and integrate multiple B210 FFT blocks per GUI refresh so the SDR
  receive buffer is less likely to overflow.
- Treat individual B210 RX overflow reports as recoverable runtime events.

## 0.1.2 - B210 Timed Stream Start

- Start the two-channel B210 RX stream with a future hardware timestamp so UHD
  can align both channels.

## 0.1.1 - B210 Startup Diagnostics

- Switched B210 startup to manual gain instead of automatic gain mode.
- Added B210 gain, read timeout, and device argument GUI inputs.
- Added clearer B210 startup error messages that identify the failing setup step.
- Added B210 hardware troubleshooting notes.

## 0.1.0 - Initial FX Correlator Baseline

- Added Tkinter GUI for interferometry input parameters.
- Added two-input FX correlator with realtime integrated cross spectrum.
- Added lag-domain interferogram display.
- Added simulated two-antenna source with coordinate-based geometric delay.
- Added initial Ettus B210/SoapySDR source adapter.
- Added Ubuntu setup notes and dependency file.
