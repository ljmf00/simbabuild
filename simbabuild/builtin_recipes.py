from simbabuild.api import api

import shutil

import simbabuild.builder_async as builder_async
import simbabuild.builder_ninja as builder_ninja


def load_recipes():

    ###########################################################################

    api.environment(
        name='default',
        systarget=api.simba.options.systarget,
        archiver=api.generator(
            name='ar',
            command='rm -f {output} && {executor} crs {output} {input}',
            executor=api.external.executable('ar'),
        ),
        linker=api.generator(
            name='link',
            command="{exe} {in} -o {out}",
            executor=api.external.executable('cc'),
        ),
        default=True,
    )

    ###########################################################################

    api.generator(
        name='ld',
        command="{exe} -r {env.LDFLAGS} -o {out} {in}",
        executor=api.external.executable('ld'),
    )

    ###########################################################################

    api.filetype(
        name='c',
        extensions=['.c', '.cc'],
        generator=api.generator(
            name='cc',
            command="{exe} -c {in} {env.CFLAGS} -o {out}",
            executor=api.external.executable('cc'),
        ),
    )

    api.filetype(
        name='cpp',
        extensions=['.cpp', '.cxx'],
        generator=api.generator(
            name='cpp',
            command="{exe} {in} {env.CXXFLAGS} -o {out}",
            executor=api.external.executable('cpp'),
        ),
    )

    api.filetype(
        name='d',
        extensions=['.d'],
        generator=api.generator(
            name='ldmd2',
            command="{executor} -c {in} {includes} {env.DFLAGS} -of={out}",
            executor=api.external.executable('ldmd2'),
        ),
    )

    ###########################################################################

    @api.finder.hook(name='default', default=True)
    async def default_find(self: api.finder, target: api.external):
        if target.kind == 'executable':
            path = shutil.which(target.external_name)
            if path:
                target.path = path
                return target

        return None

    api.builder.hook(
        name='default',
        default=True,
    )(builder_async.builder)

    api.builder.hook(
        name='ninja',
        executor=api.external.executable('ninja'),
    )(builder_ninja.builder)
