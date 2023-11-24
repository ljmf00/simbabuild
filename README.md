# simbabuild
A simple build system made in Python

## Getting started

Add this to your primary `simba.py` recipe and make it executable, so you can
run it via `simba.py`. You can add the import to the other recipes to get
type checks, using `mypy`.

```py
#!/usr/bin/env python3
from simbabuild import *
```

This bootstrap import runs the neccessary pieces to resolve recipe entries on
`import` and run the build system. If you prefer, you can always run
`simbabuild` executable and not make your recipes executable.

Here's a recipe example:

```py
executable(
    name='foo',
    sources=files('src/**/*.c'),
    includes=folders('include'),
    dependencies = {
        static_library('libfoo'),
    }
)

static_library(
    name='libfoo',
    sources=files('lib/src/**/*.c'),
    includes=folders('lib/include'),
)

alias('bar', target('foo')) # referencing to build 'bar' or 'foo' is the same
```

## Extend the build system

You can create custom builders and finders to external dependencies like the
following:

```py
@builder.hook(name='mybuilder')
async def mybuilder(self: api.builder, targets: set[api.target])
    # do build stuff
    pass

@finder.hook(name='myfinder')
async def myfinder(self: api.finder, target: api.external)
    # find the external executable by modifying the target so it will no longer
    # be seen as a forward reference.
    pass
```

The decorators are an alias to the following:

```py
async def myfinder(self: api.finder, target: api.external)
    # find the external executable by modifying the target so it will no longer
    # be seen as a forward reference.
    pass

finder(
    name='myfinder',
    hook=myfinder,
)
```

### Languages and generators

To define a new generator you can do:
```py
generator(
    name='mygenerator',
    command='{exe} -c {input} -o {output}',
    executor=external.executable('clang'),
)
```

Inside command you can use `{env.CFLAGS}` or any other variable, that are
defined in the inherited `environment` named target. To specify environment
targets you can specify it like this:

```py
environment(
    name='myenv',
    variables=bunch(
        CFLAGS=['-g', '-O3'],
    ),
    parent=environment('default'),
)
```

To attach an environment to a dependency, you can use the keyword argument
`environment`.

Generators will inherit the dependency environment or use the default
environment. Effectively, the dependency will inherit the default environment
if no environment specified.

To specify a language you create a `filetype` named target:

```py
filetype(
    extensions=['.rs'],
    generator=generator('rustc'),
)
```

Then, when you specify a source file in `executable` targets, they will be
searched by `filetype.find` or `filetype.try_find` methods. You can also
specify a specific generator for a given dependency with `generator` keyword
argument.

## Concept

All the definitions in recipes are targets. Those recipes are effectively
python functions, that register the metadata into the recipe context registry
being able to forward reference them. For example:

```py
obj1 = static_library(
    name='libfoo',
    sources=files('lib/src/**/*.c'),
    includes=folders('lib/include'),
)

obj2 = static_library('libfoo')

assert (obj1 is obj2) # they are the same (because of the first definition)
```

They can be referenced in any order, being again, the same python object:

```py
static_library('libfoo')

static_library(
    name='libfoo',
    sources=files('lib/src/**/*.c'),
    includes=folders('lib/include'),
)
```

Although if you do:

```py
static_library('libfoo')
```

At the end of reading all the recipes, the build system will yield an error of
forward reference, because this object is not complete.
