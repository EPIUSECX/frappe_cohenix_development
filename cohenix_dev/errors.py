"""Typed error types for the Cohenix developer CLI."""

from __future__ import annotations


class CohenixError(Exception):
    """User-facing failure. CLI maps this to a non-zero exit."""

    exit_code = 1


class ConfigError(CohenixError):
    exit_code = 2


class VerifyError(CohenixError):
    exit_code = 1


class RecoveryError(CohenixError):
    exit_code = 1


class DestructiveResetAborted(CohenixError):
    exit_code = 2
