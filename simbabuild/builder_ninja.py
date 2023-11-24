from __future__ import annotations

import textwrap
import re
import os

from simbabuild.api import api
from simbabuild.utility import as_list

class NinjaWriter(object):
    """
    Class for generating .ninja files.

    Note that this is emphatically not a required piece of Ninja; it's
    just a helpful utility for build-file-generation systems that already
    use Python.
    """

    def __init__(self, output, width=78):
        self.output = output
        self.width = width

    def newline(self):
        self.output.write('\n')

    def comment(self, text):
        for line in textwrap.wrap(text, self.width - 2, break_long_words=False,
                                  break_on_hyphens=False):
            self.output.write('# ' + line + '\n')

    def variable(self, key, value, indent=0):
        if value is None:
            return
        if isinstance(value, list):
            value = ' '.join(filter(None, value))  # Filter out empty strings.
        self._line('%s = %s' % (key, value), indent)

    def pool(self, name, depth):
        self._line('pool %s' % name)
        self.variable('depth', depth, indent=1)

    def rule(self, name, command, description=None, depfile=None,
             generator=False, pool=None, restat=False, rspfile=None,
             rspfile_content=None, deps=None):
        self._line('rule %s' % name)
        self.variable('command', command, indent=1)
        if description:
            self.variable('description', description, indent=1)
        if depfile:
            self.variable('depfile', depfile, indent=1)
        if generator:
            self.variable('generator', '1', indent=1)
        if pool:
            self.variable('pool', pool, indent=1)
        if restat:
            self.variable('restat', '1', indent=1)
        if rspfile:
            self.variable('rspfile', rspfile, indent=1)
        if rspfile_content:
            self.variable('rspfile_content', rspfile_content, indent=1)
        if deps:
            self.variable('deps', deps, indent=1)

    def build(self, outputs, rule, inputs=None, implicit=None, order_only=None,
              variables=None, implicit_outputs=None, pool=None, dyndep=None):
        outputs = as_list(outputs)
        out_outputs = [self.escape_path(x) for x in outputs]
        all_inputs = [self.escape_path(x) for x in as_list(inputs)]

        if implicit:
            implicit = [self.escape_path(x) for x in as_list(implicit)]
            all_inputs.append('|')
            all_inputs.extend(implicit)
        if order_only:
            order_only = [self.escape_path(x) for x in as_list(order_only)]
            all_inputs.append('||')
            all_inputs.extend(order_only)
        if implicit_outputs:
            implicit_outputs = [self.escape_path(x)
                                for x in as_list(implicit_outputs)]
            out_outputs.append('|')
            out_outputs.extend(implicit_outputs)

        self._line('build %s: %s' % (' '.join(out_outputs),
                                     ' '.join([rule] + all_inputs)))
        if pool is not None:
            self._line('  pool = %s' % pool)
        if dyndep is not None:
            self._line('  dyndep = %s' % dyndep)

        if variables:
            if isinstance(variables, dict):
                iterator = iter(variables.items())
            else:
                iterator = iter(variables)

            for key, val in iterator:
                self.variable(key, val, indent=1)

        return outputs

        def include(self, path):
            self._line('include %s' % path)

        def subninja(self, path):
            self._line('subninja %s' % path)

        def default(self, paths):
            self._line('default %s' % ' '.join(as_list(paths)))

        def _count_dollars_before_index(self, s, i):
            """Returns the number of '$' characters right in front of s[i]."""
            dollar_count = 0
            dollar_index = i - 1
            while dollar_index > 0 and s[dollar_index] == '$':
                dollar_count += 1
                dollar_index -= 1
            return dollar_count

        def _line(self, text, indent=0):
            """Write 'text' word-wrapped at self.width characters."""
            leading_space = '  ' * indent
            while len(leading_space) + len(text) > self.width:
                # The text is too wide; wrap if possible.

                # Find the rightmost space that would obey our width constraint and
                # that's not an escaped space.
                available_space = self.width - len(leading_space) - len(' $')
                space = available_space
                while True:
                    space = text.rfind(' ', 0, space)
                    if (space < 0 or
                        self._count_dollars_before_index(text, space) % 2 == 0):
                        break

                if space < 0:
                    # No such space; just use the first unescaped space we can find.
                    space = available_space - 1
                    while True:
                        space = text.find(' ', space + 1)
                        if (space < 0 or
                            self._count_dollars_before_index(text, space) % 2 == 0):
                            break
                if space < 0:
                    # Give up on breaking.
                    break

                self.output.write(leading_space + text[0:space] + ' $\n')
                text = text[space+1:]

                # Subsequent lines are continuations, so indent them.
                leading_space = '  ' * (indent+2)

            self.output.write(leading_space + text + '\n')

        def close(self):
            self.output.close()

    @staticmethod
    def escape(string: str) -> str:
        """Escape a string such that it can be embedded into a Ninja file without
        further interpretation."""
        assert '\n' not in string, 'Ninja syntax does not allow newlines'
        # We only have one special metacharacter: '$'.
        return string.replace('$', '$$')

    @staticmethod
    def expand(string, vars, local_vars={}):
        """Expand a string containing $vars as Ninja would.

        Note: doesn't handle the full Ninja variable syntax, but it's enough
        to make configure.py's use of it work.
        """
        def exp(m):
            var = m.group(1)
            if var == '$':
                return '$'
            return local_vars.get(var, vars.get(var, ''))
        return re.sub(r'\$(\$|\w*)', exp, string)

    @staticmethod
    def escape_path(word: str) -> str:
        return word.replace('$ ', '$$ ').replace(' ', '$ ').replace(':', '$:')


###############################################################################

async def builder(self: api.builder, targets: set):
    with open('build.ninja', 'w') as file:
        file.write("ninja_required_version = 1.3\n\n")

        file.write("builddir = .\n")

        rel_rootdir = os.path.relpath(
            api.simba.options.rootdir,
            start=api.simba.options.builddir,
        )
        file.write("rootdir = %s\n" % rel_rootdir)
        file.write("\n")

        visited = set()

        def visit(target):
            if target in visited:
                return

            visited.add(target)

            if isinstance(target, api.generator):
                file.write("rule %s\n" % target.name)
                file.write("  command = %s\n" % target.command)
                file.write("\n")

            if isinstance(target, api.dependency):
                if target.generator:
                    visit(target.generator)

                inputs = set()

                for dep in target.get_dependencies():
                    visit(dep)

                    dout = dep.get_output()
                    path = api.builder.rootdir_relpath(dout)
                    if dep.provider == 'internal':
                        inputs.add(os.path.join('$builddir', path))
                    elif os.path.isabs(path):
                        inputs.add(path)
                    else:
                        inputs.add(os.path.join('$rootdir', path))

                if target.provider != 'internal':
                    return

                if len(inputs) == 0:
                    return

                out = target.get_output()
                path = api.builder.rootdir_relpath(out)
                if not os.path.isabs(path):
                    path = os.path.join('$builddir', path)

                # generate target aliases
                for a in target.aliases:
                    file.write("build %s: phony %s\n" % (a, path))

                # generate the rule of this dependency
                file.write("build %s: %s %s\n" % (
                    path,
                    target.generator.name if target.generator else 'phony',
                    ' '.join(inputs),
                ))

        for target in targets:
            visit(target)

    await self.executor.run('-C', api.simba.options.builddir)
