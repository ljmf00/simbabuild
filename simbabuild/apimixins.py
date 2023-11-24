from __future__ import annotations

import asyncio

from simbabuild.api import api
from simbabuild.utility import status


class prefixed:
    """
    Defines a target mixin class for a named target.  This is used to prevent
    name clashes across target subtypes.
    """
    def target_name(self):
        return '%s::%s' % (self.__class__.__name__, self.name)


class nofwdref:
    """
    Defines a target mixin class for a target that doesn't have forward
    references.
    """

    def is_forward_ref(self):
        return False


class expandable:
    """
    Defines a class mixin for an expandable target
    """

    _prepared: bool = False
    _expanded: bool = False
    _expand_lock: asyncio.Lock

    @property
    def expanded(self):
        return self._expanded

    @property
    def prepared(self):
        return self._prepared

    async def prepare(self):
        if self._prepared:
            try:
                await self._expand_lock.acquire()
                return self
            finally:
                self._expand_lock.release()

        api._.report_status("Preparing '%s'..." % self)

        try:
            self._expand_lock = asyncio.Lock()
            self._prepared = True

            await self._expand_lock.acquire()

            if '_prepare' in dir(self.__class__):
                await self._prepare()

            return self
        finally:
            self._expand_lock.release()

    async def expand(self):
        if self._expanded:
            try:
                await self._expand_lock.acquire()
                return self
            finally:
                self._expand_lock.release()

        api._.report_status("Expanding '%s'..." % self)

        try:
            self._expanded = True

            if self._prepared:
                was_prepared = True
            else:
                self._expand_lock = asyncio.Lock()
                self._prepared = True
                was_prepared = False

            await self._expand_lock.acquire()

            if not was_prepared and '_prepare' in dir(self.__class__):
                await self._prepare()

            if '_resolve' in dir(self.__class__):
                await self._resolve()

            api._.pool.add(self)

            return self
        finally:
            self._expand_lock.release()
