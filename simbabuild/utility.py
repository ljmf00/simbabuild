from __future__ import annotations
from typing import Any, NoReturn

import os
import sys
import reprlib
import contextlib
import platform
import asyncio
import rich.console
import rich.traceback


"""
Registers how many errors we got so far, during the run of simba.
"""
haserror: int = 0

"""
Debugging flag to enable verbose logging.
"""
debugging: bool = False

"""
Errors console
"""
error_console = rich.console.Console(stderr=True)
rich.traceback.install(console=error_console, show_locals=True)

"""
Output console
"""
console = rich.console.Console()
console_status = error_console.status('Initializing...', spinner='line')

def status(msg: str) -> None:
    """
    Update the status.
    """

    if debugging:
        error_console.log(msg)

    console_status.update(msg)


def log(msg: str) -> None:
    """
    Verbose logging.

    Enabled with `simbabuild.utility.debugging = True`
    """

    if not debugging:
        # not in debug
        return

    error_console.log("debug log: %s" % msg)


def stop_on_error() -> NoReturn | None:
    """
    Stop the program on any raised error
    """

    if haserror == 0:
        # no errors short circuit
        return

    if sys.exc_info()[0] is not None:
        # raise unhandled exceptions (when stop_on_error is called on finally)
        error_console.print_exception(show_locals=True)

    sys.exit(1)


def error(reason: str, *, file=None, line=None):
    global haserror
    haserror = haserror + 1

    prefix = 'Error'
    if file:
        prefix = prefix + ' in ' + str(file)
        if line:
            prefix = prefix + ' at ' + str(line)

    error_console.log("%s: %s" % (prefix, reason))


def fatal(reason: str, *, file=None, line=None) -> NoReturn:
    error(reason, file=file, line=line)
    sys.exit(1)


class bunch:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __setitem__(self, key: str, value: Any) -> bunch:
        setattr(self, key, value)
        return self

    def __iter__(self):
        for k in vars(self):
            if not k.startswith('_'):
                yield k, getattr(self, k)

    @reprlib.recursive_repr()
    def __repr__(self) -> str:
        return str(dict(self))


@contextlib.contextmanager
def chdir(path: str):
    cur = os.getcwd()

    try:
        yield os.chdir(path)
    finally:
        os.chdir(cur)


def get_system_target():
    arch = platform.machine().lower()
    system = platform.system().lower()
    if system == 'darwin':
        vendor = 'apple'
        env = 'macho'
    else:
        vendor = 'pc'
        if system == 'linux':
            env = 'gnu'
        else:
            env = 'elf'

    return '%s-%s-%s-%s' % (
        arch,
        vendor,
        system,
        env,
    )


def as_list(input: Any) -> list:
    if input is None:
        return []
    if isinstance(input, list):
        return input
    return [input]

async def async_shell(cmd, *, report: bool = True, exit_on_error: bool = True):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if report:
        if stdout or stderr:
            console_status.stop()
            console.print(console_status.status)

        if stdout:
            console.print(stdout.decode())
        if stderr:
            error_console.print(stderr.decode())

    if proc.returncode != 0 and exit_on_error:
        fatal("Command \"%s\" exited with %s code." % (
            cmd.replace('"', '\"'), proc.returncode)
        )

    if report and (stdout or stderr):
        console.print()
        console_status.start()

    return (proc, stdout, stderr)
