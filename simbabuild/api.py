from __future__ import annotations

from simbabuild.context import Context, gcontext
from simbabuild.utility import (
    bunch, error, fatal, chdir, stop_on_error, status, async_shell,
)

import os
import sys
import inspect
import asyncio


class API(type):
    """
    Metaclass for the api decorator class
    """

    def __call__(cls, obj) -> None:
        assert (obj.__name__ != 'context')

        if hasattr(obj, '__func__'):
            obj = staticmethod(obj)

        setattr(gcontext, obj.__name__, obj)
        return obj

    def __getattr__(cls, key):
        return getattr(gcontext, key)


class api(metaclass=API):
    """
    Defines the accessible objects from the public API of the build system.

    This can be used as a decorator to mark an object as exported.
    """
    pass


###############################################################################

from simbabuild.builtin_recipes import load_recipes  # noqa: E402
from simbabuild.apiutility import (  # noqa: E402
    Target, TargetValidator, VariableGetter, expand_files,
)
from simbabuild.apimixins import expandable, prefixed, nofwdref  # noqa: E402

api(bunch)
api(error)
api(fatal)


class TargetPool:
    all: set = set()
    skipped: set = set()
    running: set = set()
    failed: set = set()
    finished: set = set()

    def add(self, target):
        self.all.add(target)
        return True

    def skip(self, target):
        if self.add(target):
            self.skipped.add(target)

    def progress_str(self):
        l_all = len(self.all)
        l_ski = len(self.skipped)
        l_run = len(self.running)
        l_fai = len(self.failed)
        l_fin = len(self.finished)
        l_com = l_ski + l_fai + l_fin
        l_rem = l_all - (l_com + l_run)

        if l_all == 0:
            percentage = 0.0
        else:
            percentage = (l_com / l_all) * 100.0

        return "[%.2f%% [yellow]%s[/]/[red]%s[/] [cyan]%s[/]/[green]%s[/]/[magenta]%s[/]/%s]" % (
            percentage,
            l_ski,
            l_fai,

            l_rem,
            l_run,
            l_com,
            l_all,
        )


@api
class _:
    """
    Represents the internal state used for Simba
    """

    visited: set = set()
    registry: dict = dict()

    finders: set = set()
    filetypes: dict = dict()
    phase: str = 'preload'
    pool: TargetPool

    def __init__(self) -> None:
        _.context = gcontext
        _.pool = TargetPool()

    async def load(self):
        _.phase = 'load'

        load_recipes()
        self.include(gcontext.__file__)

        stop_on_error()

        _.phase = 'prepare'
        for k, target in self.registry.items():
            await self.prepare(target)

        stop_on_error()

        _.phase = 'postload'

    @classmethod
    def report_status(cls, msg: str):
        status('%s %s' % (cls.pool.progress_str(), msg))

    @classmethod
    def ensure_can_create(cls, obj):
        if cls.phase == 'prepare':
            obj.fatal("can't create object while on '%s' phase" % cls.phase)

    @classmethod
    async def prepare(cls, target: target):
        if target in cls.visited:
            return

        if 'is_forward_ref' in dir(target.__class__) and target.is_forward_ref():
            target.fatal("forward reference")

        cls.visited.add(target)
        await target.prepare()

    @classmethod
    def update(cls, obj: bunch) -> bunch:
        tname = obj.target_name()
        override = False
        default = False

        if 'override' in obj.__dict__:
            override = obj.override
            delattr(obj, 'override')

        if 'default' in obj.__dict__:
            default = obj.default
            delattr(obj, 'default')

        if tname in cls.registry:
            robj = cls.registry[tname]
            if hasattr(robj, '_expanded') and robj._expanded:
                robj.fatal("can't update an expanded object")

            robj.__class__ = obj.__class__

            if default:
                robj.__class__.default = robj
            elif robj.name == 'default' and not hasattr(robj.__class__, 'default'):
                robj.__class__.default = robj

            for key, value in obj:
                if key == 'name':
                    continue

                if key.startswith('_'):
                    obj.error("forbidden field", field=key)

                if hasattr(robj, key) and getattr(robj, key) != value and not override:
                    robj.error("already exists (use override=True)", field=key)

                setattr(robj, key, value)

            return robj

        cls.registry[tname] = obj
        if default or \
           (obj.name == 'default' and not hasattr(obj.__class__, 'default')):
            obj.__class__.default = obj

        _.ensure_can_create(obj)
        return obj

    @classmethod
    def include(cls, path: str) -> None:
        stop_on_error()

        if not os.path.isabs(path):
            path = os.path.join(
                os.path.dirname(cls.context.__file__),
                path
            )

        if os.path.isdir(path):
            path = os.path.join(path, 'simba.py')

        if path in cls.visited:
            return

        cls.visited.add(path)
        with cls.context as child:
            try:
                cls.context = child
                child.__file__ = path
                with open(child.__file__, 'r') as file:
                    exec(
                        compile(
                            file.read(),
                            child.__file__,
                            'exec'
                        ),
                        child.__dict__,
                    )
            finally:
                cls.context = child.parent


@api
def include(path: str) -> None:
    """
    Includes another child recipe to the current recipe.

    Analogous to the import statement.
    """

    _.include(path)


@api
class target(expandable, bunch, metaclass=Target):
    """
    Defines a generic target.

    ---
    target(
        **bunch,

        name: str,

        default?: bool,
        override?: bool,
        force?: bool,
    )
    ---

    The user can use this target type to forward reference some target with
    a specific name.

    A target is defined by a bunch of attributes, validated afterwards, when
    the forward reference is resolved, so they can be cross-referenced without
    problems of definition order.
    """

    # the hidden context
    _context: Context
    # the frame where the target was defined
    _frame: inspect.Traceback

    def error(self, reason: str, *, field=None):
        prefix = str(self)
        if field:
            prefix = '%s.%s' % (prefix, field)

        if hasattr(self, '_frame'):
            error(
                '%s: %s' % (prefix, reason),
                file=self._frame.filename,
                line=self._frame.lineno
            )
        else:
            error('%s: %s' % (prefix, reason))

    def fatal(self, reason: str, *, field=None):
        self.error(reason, field=field)
        sys.exit(1)

    def is_forward_ref(self):
        """
        Checks if the target is not yet defined (forward reference).

        Forward references are used when we reference a target but didn't
        define it yet.  This should be mandatory, by default, right before
        prepare stage.
        """

        for key, value in self:
            if key.startswith('_'):
                continue

            if key != 'name':
                return False

        return True

    def is_normal_target(self):
        """
        Checks whether the target is a normal target or another type of target,
        like a named target.  Normal targets match the raw name of the target.
        """

        return self.target_name() == self.name

    def target_name(self):
        """
        Target name used by the user to reference externally.  This might
        differ from the name (raw name).
        """

        return self.name

    async def _prepare(self):
        """
        Prepare the target

        This defines the prepare stage, where the target is validated/checked
        for invalid or unrecognized attributes and emplace default/implicit
        attributes.
        """

        with TargetValidator(self):
            pass

    async def _resolve(self):
        """
        Resolve the target

        At this stage, we resolve missing information on the target.  This
        information might be the current path of an external local executable
        in the system, wether the dependency has a matching generator, etc...

        This should include expensive validation steps, so, a target not
        affected by the build, wont be resolved.
        """

        pass

    def __str__(self):
        return self.target_name()


@api
class namedtarget(prefixed, target):
    """
    Named target.

    It's a target with the name of the subtype target prefixed.
    """

    pass


@api
class path(nofwdref, namedtarget):
    """
    Defines a generic path as a target

    This target can be used as a dependency or to define a path for a given
    target.

    They are relative to the recipe location.
    """

    def get_path(self):
        if os.path.isabs(self.name):
            return self.name
        ctxfolder = os.path.dirname(self._context.__file__)
        return os.path.join(ctxfolder, self.name)

    async def generate(self):
        return self.name


@api
class file(path):
    """
    Defines a file path as a target
    """

    pass


@api
class folder(path):
    """
    Defines a folder path as a target
    """

    pass


@api
def folders(*paths):
    return {folder(p) for p in paths}


@api
class files(expandable, bunch):
    """
    Define a group of files.

    They can be flatten and expanded to a set of path objects.
    """

    def get_sources(self):
        return expand_files(self, self.sources)

    def __init__(self, *args):
        self.sources = args

        self._context = _.context
        self._frame = inspect.getframeinfo(inspect.stack()[1][0])


@api
class environment(namedtarget):
    async def _prepare(self):
        default_env = environment.get_default()
        required = False

        if default_env is self:
            default_env = None
            required = True
            archiver = None
            linker = None
            includes = None
            variables = None
            systarget = api.simba.options.systarget

        with TargetValidator(self) as v:
            v.field('parent', environment, required=False, default=default_env)

            if self.parent:
                systarget = self.parent.systarget
                variables = self.parent.variables
                archiver = self.parent.archiver
                linker = self.parent.linker
                includes = self.parent.includes

            v.field('systarget', str, required=required, default=systarget)
            v.field('archiver', generator, required=required, default=archiver)
            v.field('linker', generator, required=required, default=linker)
            v.field('includes', [list, set], required=False, default=includes)
            v.field('variables', [dict, bunch], required=False, default=variables)

        if self.variables is None:
            self.variables = dict()
        if self.includes is None:
            self.includes = set()


    def variable_getter(self):
        return VariableGetter(self.variables)

@api
class dependency(target):
    async def _prepare(self):
        env_default = environment.get_default()

        with TargetValidator(self) as v:
            v.field('kind', str, required=False, default='unknown')
            v.field('aliases', set, required=False, default=set())
            v.field('dependencies', set, required=False, default=set())
            v.field('provider', str, required=False, default='internal')
            v.field('generator', generator, required=False, default=None)
            v.field('nofiletype', bool, required=False, default=False)
            v.field(
                'sources',
                [files, file, set, tuple, str],
                required=False,
                default=set(),
            )
            v.field(
                'environment',
                environment,
                required=False,
                default=env_default,
            )

        if self.provider == 'local' and len(self.dependencies) > 0:
            self.fatal("'local' provider dependency can't have dependencies")

    async def _resolve(self):
        await self.environment.expand()

        if self.generator:
            await self.generator.expand()
        else:
            if self.kind == 'executable' or self.kind == 'shared_library':
                self.generator = await self.environment.linker.expand()
            elif self.kind == 'static_library':
                self.generator = await self.environment.archiver.expand()

        for dep in self.dependencies:
            await dep.expand()

    @staticmethod
    def create(name: str, *, kind: str, sources, includes: set | None = None, **kwargs):
        if 'environment' in kwargs:
            env = kwargs['environment']
            del kwargs['environment']
        else:
            env = environment('default')

        env = environment(
            '%s::%s' % (kind, name),
            includes=includes,
            parent=env,
        )

        return dependency(
            name=name,
            environment=env,
            sources=sources,
            kind=kind,
            **kwargs,
        )

    @staticmethod
    @api
    def executable(name: str, *, sources, **kwargs):
        return dependency.create(name, kind='executable', sources=sources, **kwargs)

    @staticmethod
    @api
    def static_library(name: str, *, sources, **kwargs):
        return dependency.create(name, kind='static_library', sources=sources, **kwargs)

    @staticmethod
    @api
    def shared_library(name: str, *, sources, **kwargs):
        return dependency.create(name, kind='shared_library', sources=sources, **kwargs)

    async def get_output(self):
        ctxfolder = os.path.dirname(self._context.__file__)
        isources = self.get_sources()
        source = await anext(isources, None)

        if self.provider == 'local':
            return source

        if not source or \
           await anext(isources, None) or \
           self.kind == 'executable' or \
           self.kind == 'static_library' or \
           self.kind == 'shared_library':
            return os.path.join(
                ctxfolder,
                self.name + generator.kind_to_ext(self.kind),
            )
        elif self.generator:
            return await anext(self.generator.get_output(source, kind=self.kind))
        else:
            ft = await filetype.find(source).expand()
            return await anext(ft.generator.get_output(source, kind=self.kind))

    async def get_sources(self):
        async for f in expand_files(self, self.sources):
            yield f

    async def get_aliases(self):
        for alias in self.aliases:
            yield await target(alias).expand()

    async def get_dependencies(self):
        if self.provider == 'local':
            return

        for dep in self.dependencies:
            yield await dep.expand()

        async for source in self.get_sources():
            ft = filetype.try_find(source)
            if self.kind == 'executable' and ft is None:
                self.fatal("no filetype for '%s'" % source)

            if self.nofiletype or ft is None:
                dep = dependency(
                    name=source,
                    sources=source,
                    environment=self.environment,
                    provider='local',
                    kind='source',
                )
                yield await dep.expand()
            else:
                await ft.expand()
                out = await anext(ft.generator.get_output(source, kind='object'))
                dep = dependency(
                    name=out,
                    sources=source,
                    environment=self.environment,
                    generator=ft.generator,
                    nofiletype=True,
                    kind='object',
                )
                yield await dep.expand()

    async def generate(self):
        await self.expand()

        tasks = set()

        try:
            async with asyncio.TaskGroup() as tg:
                async for d in self.get_dependencies():
                    task = tg.create_task(d.generate())
                    tasks.add(task)
        except ExceptionGroup as eg:
            for e in eg.exceptions:
                raise e

        inputs = [t.result() for t in tasks]
        out = await self.get_output()

        if self.provider != 'local' and self.generator:
            return await self.generator.generate(
                inputs,
                environment=self.environment,
                output=out
            )

        return out



@api
class project(namedtarget):
    async def _prepare(self):
        with TargetValidator(self) as v:
            v.field('license', file, required=False)
            v.field('description', str, required=False)
            v.field('metadata', bunch, required=False)


@api
class generator(namedtarget):
    async def _prepare(self):
        with TargetValidator(self) as v:
            v.field('command', str, required=True)
            v.field('executor', dependency, required=True)
            v.field('depfile', str, required=False, default=None)
            v.field('deptype', str, required=False, default=None)
            v.field('rspfile', str, required=False, default=None)
            v.field('rspcontent', str, required=False, default=None)
            v.field('includefmt', str, required=False, default="-I '%s'")
            v.field('variables', dict, required=False, default=dict())
            v.field(
                'description',
                str,
                required=False,
                default='%s {out}' % self.name.upper(),
            )
            v.field(
                'output',
                str,
                required=False,
                default='{filename}{kindext}',
            )

    async def _resolve(self):
        await self.executor.expand()

    @staticmethod
    def kind_to_ext(kind: str):
        if kind == 'executable':
            return ''
        elif kind == 'static_library':
            return '.a'
        elif kind == 'shared_library':
            return '.so'
        elif kind == 'object':
            return '.o'
        else:
            return '.out'

    def get_format(self, string, input, environment, output):
        if isinstance(input, str):
            input = list(input)

        input_str = ' '.join(["'%s'" % i for i in input])
        output_str = "'%s'" % output

        return string.format_map({
            'exe': self.executor.path,
            'executor': self.executor.path,

            'in': input_str,
            'input': input_str,

            'out': output_str,
            'output': output_str,
            'outputdir': "'%s'" % os.path.dirname(output),

            'env': environment.variable_getter(),
            'environment': environment.variable_getter(),
            'includes': ' '.join([self.includefmt % i.get_path() for i in environment.includes]),
        })

    async def generate(
        self,
        input: str | list[str],
        *,
        environment: api.environment,
        kind: str = 'object',
        output: str | None = None
    ):
        if output is None:
            output = await self.get_output(input, kind=kind)

        output = builder.builddir_path(output)
        os.makedirs(os.path.dirname(output), exist_ok=True)

        _.report_status(
            "Generating %s..." % self.get_format(
                self.description, input, environment, output
            )
        )
        cmd = self.get_format(self.command, input, environment, output)
        proc, stdout, stderr = await async_shell(cmd)

        return output


    async def get_output(self, input: str | list[str], *, kind: str = 'object'):
        kindext = generator.kind_to_ext(kind)
        if isinstance(input, str):
            filename, ext = os.path.splitext(input)
            yield self.output.format(**locals())
        else:
            for input in input:
                filename, ext = os.path.splitext(input)
                yield self.output.format(*locals())


@api
class filetype(namedtarget):
    async def _prepare(self):
        with TargetValidator(self) as v:
            v.field('extensions', list, required=True)
            v.field('generator', generator, required=True)

        for e in self.extensions:
            if e in _.filetypes:
                self.fatal(
                    "target '%s' already registers '.%s'" % (
                        _.filetypes[e],
                        e,
                    )
                )
            _.filetypes[e] = self

    @classmethod
    def try_find(cls, path: str) -> filetype | None:
        root, ext = os.path.splitext(path)
        if ext in _.filetypes:
            return _.filetypes[ext]

        return None

    @classmethod
    def find(cls, path: str) -> filetype:
        found = cls.try_find(path)
        if found:
            return found

        fatal("filetype matching file '%s' not found" % path)


@api
class finder(prefixed, target):
    async def _prepare(self):
        _.finders.add(self)

    async def find(self, target: external):
        await self.__call__(self, target)


@api
class alias(target):
    pass


@api
class builder(namedtarget):
    async def _prepare(self):
        with TargetValidator(self) as v:
            v.field('executor', external, required=False)
            v.field('hook', type(lambda _: _), required=False)

    async def _resolve(self):
        if self.executor:
            await self.executor.expand()

    ###########################################################################

    @classmethod
    def builddir_path(cls, path: str):
        relpath = api.builder.rootdir_relpath(path)
        if os.path.isabs(relpath):
            return relpath

        builddir = api.simba.options.builddir
        return os.path.join(builddir, relpath)

    @classmethod
    def rootdir_relpath(cls, path: str):
        if os.path.isabs(path):
            abspath = os.path.abspath(path)
            try:
                return os.path.relpath(abspath, start=gcontext.simba.options.rootdir)
            except ValueError:
                # not in rootdir
                return abspath

        # must be already relative to rootdir
        return path

    async def build(self, targets: list):
        await self.expand()

        if api.simba.options.dry_run:
            for t in targets:
                await t.expand()
            return

        with chdir(api.simba.options.builddir):
            await self.__call__(self, targets)


@api
class external(namedtarget, dependency):
    def target_name(self):
        return 'external.%s::%s' % (self.kind, self.external_name)

    async def _prepare(self):
        with TargetValidator(self) as v:
            v.field('kind', str, required=False, default='unknown')
            v.field('provider', str, required=True)
            v.field('external_name', str, required=True)
            v.field('path', str, required=False)

    async def _resolve(self):
        if self.path:
            return

        for f in _.finders:
            if await f.find(self):
                return

        if not self.path:
            raise TypeError("can't resolve target '%s'" % self)

    async def run(self, *args):
        if self.kind != 'executable':
            self.fatal("not runnable")
        proc = await asyncio.create_subprocess_exec(
            self.path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        return await proc.communicate()

    @staticmethod
    def get(name: str, kind: str, **kwargs):
        return external(
            name='%s:%s' % (kind, name),
            external_name=name,
            provider='local',
            kind=kind,
            **kwargs,
        )

    @staticmethod
    def executable(name: str, **kwargs):
        return external.get(name, kind='executable')

    @staticmethod
    def library(name: str, **kwargs):
        return external.get(name, kind='library')

    @staticmethod
    def static_library(name: str, **kwargs):
        return external.get(name, kind='static_library')

    @staticmethod
    def shared_library(name: str, **kwargs):
        return external.get(name, kind='shared_library')
