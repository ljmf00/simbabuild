from __future__ import annotations

from simbabuild.api import api, _
from simbabuild.context import gcontext

import simbabuild.utility
from simbabuild.utility import (
    console, status, error_console, console_status, bunch, get_system_target
)

import argparse
import os
import sys
import asyncio
import rich.live
import rich.tree
import rich.traceback


###############################################################################

async def build() -> None:
    _.report_status('Building...')

    builddir = api.simba.options.builddir
    os.makedirs(builddir, exist_ok=True)

    if _.context.simba.options.targets:
        tgts = {api.target(t) for t in _.context.simba.options.targets}
    else:
        tgts = {v for k, v in dict(_.registry).items()}

    builder_name = api.simba.options.builder
    if builder_name == 'default':
        await api.builder.default.build(tgts)
    else:
        builder = api.builder(builder_name)
        if builder.is_forward_ref():
            builder.fatal("doesn't exist")

        await builder.build(tgts)


async def tree() -> None:
    _.report_status('Resolving the tree...')

    nodes = dict()

    async def visit(obj):
        if obj not in nodes:
            nodes[obj] = bunch(parent=dict(), children=dict())
        node = nodes[obj]

        async def pvisit(parent):
            if not parent:
                return
            if parent in node.parent:
                return

            cnode = await visit(parent)
            node.parent[parent] = cnode
            cnode.children[obj] = node

        async def cvisit(child):
            if not child:
                return
            if child in node.children:
                return

            cnode = await visit(child)
            node.children[child] = cnode
            cnode.parent[obj] = node

        if isinstance(obj, api.environment):
            await pvisit(obj.parent)
            await cvisit(obj.archiver)
            await cvisit(obj.linker)
        elif isinstance(obj, api.external):
            pass
        elif isinstance(obj, api.dependency):
            await cvisit(obj.generator)
            async for a in obj.get_aliases():
                await cvisit(a)
            async for dep in obj.get_dependencies():
                await cvisit(dep)
        elif isinstance(obj, api.filetype):
            await cvisit(obj.generator)
        elif isinstance(obj, api.generator):
            await cvisit(obj.executor)
        elif isinstance(obj, api.builder):
            await cvisit(obj.executor)

        return node

    for k, v in dict(_.registry).items():
        await visit(await v.expand())

    tree = rich.tree.Tree('')
    on_tree = set()

    def add_tree(tree, k, v):
        tree = tree.add(str(k))
        if k in on_tree:
            return

        on_tree.add(k)

        for k, v in v.children.items():
            add_tree(tree, k, v)

    for k, v in nodes.items():
        if len(v.parent):
            continue

        add_tree(tree, k, v)

    console.print(tree)


async def check() -> None:
    _.report_status('Checking...')

    for k, v in dict(_.registry).items():
        await v.expand()


###############################################################################


def norun() -> None:
    pass


def run() -> None:
    # self destruct this object to avoid being run again
    global run
    run = norun

    parser = argparse.ArgumentParser(
        prog='simba',
        description='A simple build system',
    )
    parser.set_defaults(command_function=build)

    parser.add_argument('-D', '--rootdir', type=str, default='.')
    parser.add_argument('-B', '--builddir', type=str, default='builddir')
    parser.add_argument('-b', '--builder', type=str, default='default')
    parser.add_argument('-t', '--systarget', type=str, default=get_system_target())
    parser.add_argument('-r', '--recipe-file', type=str, default='simba.py')
    parser.add_argument('-T', '--targets', type=set, default={})
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-d', '--dry-run', action='store_true')

    subparsers = parser.add_subparsers()
    parser_build = subparsers.add_parser('build')
    parser_build.set_defaults(command_function=build)

    parser_tree = subparsers.add_parser('tree')
    parser_tree.set_defaults(command_function=tree)

    parser_tree = subparsers.add_parser('check')
    parser_tree.set_defaults(command_function=check)

    gcontext.simba = bunch(options=parser.parse_args(namespace=bunch))
    simbabuild.utility.debugging = gcontext.simba.options.verbose
    rich.traceback.install(
        console=error_console,
        show_locals=simbabuild.utility.debugging,
    )

    live_context = rich.live.Live(
        console=console,
        transient=True,
        refresh_per_second=4,
    )

    try:
        console_status.start()
        status('Setup context...')

        gcontext.simba.options.rootdir = os.path.abspath(
            gcontext.simba.options.rootdir
        )
        gcontext.simba.options.builddir = os.path.abspath(
            gcontext.simba.options.builddir
        )

        gcontext.__file__ = os.path.abspath(
            os.path.join(
                gcontext.simba.options.rootdir,
                gcontext.simba.options.recipe_file,
            )
        )

        async def async_run():
            status('Load recipes...')
            await _().load()
            await gcontext.simba.options.command_function()

        asyncio.run(async_run())
    finally:
        console_status.stop()

    sys.exit(0)

run()
