from __future__ import annotations
from typing import NoReturn

from simbabuild.utility import fatal, bunch

import inspect
import copy


class Context(bunch):
    """
    Defines the context inside a recipe
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.parent = None
        self.children = list()

    def __enter__(self) -> Context:
        child = copy.copy(self)
        child.parent = self
        child.children = list()

        self.children.append(child)

        # restrict parent context to set new attributes

        def unsupported(*args, **kwargs) -> NoReturn:
            frame = inspect.getframeinfo(inspect.stack()[1][0])
            fatal(
                'doing an unsupported operation on the context object',
                file=frame.filename,
                line=frame.lineno
            )

        self.__slots__ = []
        self.__setattr__ = unsupported
        self.__delattr__ = unsupported
        self.__call__ = unsupported

        return child

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


"""
Global context
"""
gcontext = Context()
