"""Entry point for the radio interferometry GUI."""

from multiprocessing import freeze_support

from radio_interferometer.gui import main


if __name__ == "__main__":
    freeze_support()
    main()
