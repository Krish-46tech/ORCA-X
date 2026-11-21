"""Exceptions shared by NOAA data providers."""


class NOAAError(RuntimeError):
    """A NOAA provider request or payload could not be used."""
