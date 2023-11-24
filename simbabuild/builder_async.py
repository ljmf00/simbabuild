from __future__ import annotations

import asyncio

from simbabuild.api import api
from simbabuild.utility import error_console, console_status


async def builder(self: api.builder, targets: set):
    tasks = set()

    try:
        async with asyncio.TaskGroup() as tg:
            for t in targets:
                if not t.is_normal_target():
                    continue
                if isinstance(t, api.external):
                    continue

                task = tg.create_task(t.generate())
                tasks.add(task)
    except ExceptionGroup as eg:
        for e in eg.exceptions:
            raise e
