"""Terminal output helpers. Flush so CI logs stay in order with subprocesses."""

from __future__ import annotations

CRED = "\033[31m"
CGRN = "\33[92m"
CYLW = "\33[93m"
CBLU = "\33[94m"
reset = "\033[0m"


def cprint(*args: object, level: int = 1) -> None:
    message = " ".join(map(str, args))
    if level == 1:
        print(CRED, message, reset, flush=True)
    elif level == 2:
        print(CGRN, message, reset, flush=True)
    elif level == 3:
        print(CYLW, message, reset, flush=True)
    else:
        print(CBLU, message, reset, flush=True)


def plain(*args: object) -> None:
    print(" ".join(map(str, args)), flush=True)
