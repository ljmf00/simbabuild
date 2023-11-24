from __future__ import annotations
from typing import Any

from simbabuild.api import api
from simbabuild.utility import status, bunch, error, fatal, stop_on_error

import os
import inspect
import glob


async def expand_files(obj: api.target, sources):
    ctxfolder = os.path.dirname(obj._context.__file__)

    if isinstance(sources, str):
        glob_path = os.path.join(ctxfolder, sources)
        for f in glob.iglob(glob_path, recursive=True, include_hidden=True):
            yield f
    elif isinstance(sources, api.files):
        async for f in sources.get_sources():
            yield f
    elif isinstance(sources, api.file):
        expander = expand_files(sources, sources.name)
        yield await anext(expander)

        if next(expander, None):
            sources.fatal("file expands a glob, use 'files' instead")
    elif isinstance(sources, set) or isinstance(sources, list) or \
         isinstance(sources, tuple):
        for source in sources:
            async for f in expand_files(obj, source):
                yield f
    else:
        obj.error("source of type '%s' can't be expanded" % type(sources))


    stop_on_error()


class TargetValidator:
    """
    A context manager used to validate a target.

    This validator defines utility to easily define what a valid target would
    look like, so we can add readable checks to attributes.
    """

    """
    Object being validated
    """
    obj: api.target

    """
    Fields required by the target
    """
    fields: list[str]

    def __init__(self, obj: api.target):
        self.obj = obj
        self.fields = list()

    def field(
        self,
        fieldname: str,
        fieldtypes: set[type] | list[type] | type,
        *,
        required: bool = True,
        default: Any = None,
    ):
        """
        Validate a field

        This helper defines how a field should be valid in the given target.
        It matches for type, wether this is a required/mandatory field and
        have a default, in the case of missing it.
        """

        self.fields.append(fieldname)

        if not hasattr(self.obj, fieldname) or getattr(self.obj, fieldname) is None:
            if required:
                self.obj.error("field is required", field=fieldname)
                return

            setattr(self.obj, fieldname, default)
            return

        field = getattr(self.obj, fieldname)
        if isinstance(fieldtypes, type):
            fieldtypes = [fieldtypes]

        for t in fieldtypes:
            if isinstance(field, t):
                return

        error(
            "field '%s(%s)' expected types %s, but got %s" % (
                self.obj, fieldname,
                fieldtypes, type(field),
            )
        )

    def __enter__(self) -> TargetValidator:
        self.field('name', str, required=True, default='default')
        self.field('expanded', bool, required=False, default=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        for k, v in self.obj:
            if k.startswith('_'):
                continue
            if k not in self.fields:
                error(
                    "unrecognized field '%s.%s'" % (self.obj, k)
                )

        stop_on_error()


class Target(type):
    """
    Metaclass that defines how a target type behaves.
    """

    def hook(cls, name: str, **kwargs):
        """
        Target hook decorator

        Any target that defines a hook, uses this decorator to wrap the hook
        and add it to the target definition.
        """

        def _hook(obj):
            # this is the actual decorator function, so we can add attributes
            # to the decorator as keywords.

            _obj = cls(name=name, hook=obj, **kwargs)
            _obj.__call__ = obj

            # return the object being wrapped
            return _obj

        # return the wrapping object, so it get called by the decorator syntax.
        return _hook

    def __call__(cls, name: str, **kwargs):
        """
        Create or reference a target

        This function is responsible for target creation or reference.  It
        internally updates the target registry according to existance of a
        target with the same name.

        Emplaces some hidden attributes to be able to locate the target and
        attach the correct context.
        """

        obj = bunch(name=name, **kwargs)
        obj.__class__ = cls
        api._.report_status("Creating target '%s::%s'" % (cls.__name__, obj.name))

        robj = api._.update(obj)
        robj._context = api._.context
        robj._frame = inspect.getframeinfo(inspect.stack()[1][0])

        return robj

    def get_default(cls):
        if hasattr(cls, 'default') and cls.default:
            return cls.default

        fatal("can't find a default for '%s'" % cls.__name__)


class VariableGetter(object):
    """
    Safe variable getter.  This implement item get interface to safely get
    any value from the stored variables dictionary.
    """

    """
    Stored variables
    """
    variables: dict[str, str]

    def __init__(self, variables: dict[str, str]):
        self.variables = variables

    def __getattr__(self, key):
        return self.get(key)

    def __getitem__(self, key):
        return self.get(key)

    def get(self, key, default: str = ''):
        if key in self.variables:
            return self.variables[key]

        return default
