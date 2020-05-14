from pathlib import Path, WindowsPath, PosixPath
import json
from importlib.util import find_spec
from importlib.machinery import BuiltinImporter
import sys
import ast
from copy import deepcopy, copy
from itertools import chain

import os
from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List, Optional, Dict, Any

# from pydeps.target import Target
# from pydeps import pydeps
# from pydeps.py2depgraph import py2dep

from .utils import Logger
from findimports import find_imports, ImportInfo, ModuleGraph

# because Path does subclassing v weird

# class PosixPathWrapper(PosixPath):
#     def _init(self, is_none):
#         self._none = is_none
#
#     @property
#     def python_file(self):
#         if self._none:
#             # none paths are not python files
#             return False
#         return self.suffix in ['.py', 'pyc']
#
# class WindowsPathWrapper(WindowsPath):
#     def _init(self, is_none):
#         self._none = is_none
#
#     @property
#     def python_file(self):
#         if self._none:
#             # none paths are not python files
#             return False
#         return self.suffix in ['.py', 'pyc']
#
# class PathWrapper(Path):
#
#     def __new__(cls, *args, **kwargs):
#         none = False
#         if args[0] is None:
#             args = list(args)
#             args[0] = ""  # keep Path happy
#             none = True
#
#         if cls is PathWrapper:
#             cls = WindowsPathWrapper if os.name == 'nt' else PosixPathWrapper
#         self = cls._from_parts(args, init=False)
#         if not self._flavour.is_supported:
#             raise NotImplementedError("cannot instantiate %r on your system"
#                                       % (cls.__name__,))
#         self._init(none)
#         return self

_Common_Exception = "find_spec system call raised an "

class SpecWrapper(Logger):

    _NAME = "SpecWrapper"

    # normal errors
    ERROR_NOT_FOUND = "Module could not be found in path"
    ERROR_SYSTEM_LIBRARY = "Module is a system library"
    # exceptions
    ERROR_EXCEPTION = _Common_Exception
    ERROR_ATTRIBUTE_EXCEPTION = f"{_Common_Exception}AttributeError"
    ERROR_MODULE_NOT_FOUND_EXCEPTION = f"{_Common_Exception}ModuleNotFoumdError"
    ERROR_VALUE_EXCEPTION = f'{_Common_Exception}ValueError'

    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.members = None
        self.spec = None
        self.error = None

        self._resolve_spec()

    def _find_spec(self, name):
        dlog = self.gen_dlog("_find_spec")

        if self.error:
            dlog(f'Module "{name}" has error, not finding spec')
            return (name, None)

        spec = None
        exception = None
        error = None

        try:
            spec = find_spec(name)
            # clear previous errors on success
        except AttributeError as e:  # __future__ crashes find_spec lol
            error = self.ERROR_ATTRIBUTE_EXCEPTION
            exception = e
        except ModuleNotFoundError as e:  # seen sometimes
            error = self.ERROR_MODULE_NOT_FOUND_EXCEPTION
            exception = e
        except ValueError as e:
            error = self.ERROR_VALUE_EXCEPTION
            exception = e


        if spec is None and '.' in name:
            # might be a X from Y situation rendered as X.Y, remove a dot and try that as the module
            (maybe_module, new_member) = name.rsplit('.', 1)
            dlog(f'Module "{name}" can\'t be found, trying {maybe_module}')

            return self._find_spec(maybe_module)

        if exception:
            self.error = error
            dlog(f'name "{self}" raised: {exception}')

        return (name, spec)


    def _resolve_spec(self):
        dlog = self.gen_dlog("_resolve_spec")
        dlog(f"{self.name}")
        (found_name, spec) = self._find_spec(self.name)

        if spec:
            # dlog(f'Checking if spec is system spec: {spec}')
            if spec.origin and 'site-packages' not in spec.origin:
                # builtin case 1
                dlog(f'Module "{self.name}" is not in sitepackages, it is a builtin.')
                self.error = self.ERROR_SYSTEM_LIBRARY
            elif spec.loader and spec.loader is BuiltinImporter:
                # builtin case 2
                dlog(f'Module "{self.name}" uses the buildin importer.')
                self.error = self.ERROR_SYSTEM_LIBRARY

            # we're importing a submodule
            if found_name != self.name:
                members = self.name
                members = members.replace(found_name, "")

                self.members = members.strip(".")

                dlog(f'{self.name} -> {found_name}; {self.members}')
                self.name = found_name

            self.spec = spec
        else:
            dlog(f'Module {self.name} does not appear to be installed in current path.')

    @property
    def origin(self):
        return getattr(self.spec, "origin", None)

    @property
    def is_error(self):
        return self.error != None

    def __str__(self):
        base = f'{self.name}|'
        if self.is_error:
            return f'{base}Err[{self.error}]'
        return f'{base} {self.spec}'

    def __repr__(self):
        return str(self)

class PrintCtx(object):
    ctx_obj: str = None
    in_statement: bool = False
    line_number: Optional[int] = None


# todo: Make a 2nd Import helper object that wraps the _act_ of importing a library
# todo: instead of the Import <x> statement in the AST. One Import statement can generate
# todo: many import actions (from X import a, b, c, d). This is why I've been keeping track of
# todo: imports seperately, because each a, b, c, d have different line# and import implications.
class ImportContext(Logger):
    """ Helper object to track where an import comes from and get info about it """

    # AST definitions we care about:
    # | Import(alias* names)
    # | ImportFrom(identifier? module, alias* names, int? level)
    #
    # An identifier is just a str, I don't know what level does (and don't care?) - will add a warning
    # Alias def: alias = (identifier name, identifier? asname)

    _NAME = "ImportContext"

    # contexts
    Source_Local = 'Local' # direct child of this node, not seen "above" this context
    Source_Above = 'Previous' # defined in a scope "outside / above" this one

    _mode_import = "import"
    _mode_import_from = "import from"

    @staticmethod
    def node_is_import(node):
        return node.__class__ in [ast.ImportFrom, ast.Import]

    def __init__(self, node: ast.AST, parent_wrapper, src: str, *kwargs):
        super().__init__(*kwargs)
        # print(f'ImportContex({node}m {parent_wrapper}, {src})')
        if not self.node_is_import(node):
            raise ValueError(f"ImportContext only supports Import and Import from. Not: {node}")

        self._parent = parent_wrapper
        self._node = node
        self._src = src

    def re_contextualize(self, new_source):
        # print(f'ImportContex.re_contextualize({new_source})')
        c = copy(self)
        c._src = new_source
        return c

    @property
    def is_imp(self):
        return self._node.__class__ is ast.Import

    # def is_imp_frm(self):
    #     return self._node.__class__ is ast.ImportFrom

    @property
    def names(self) -> List[str]:
        # full names, may or may not be modules
        if self.is_imp:
            return [name.name for name in self._node.names]

        module_str = ''
        if hasattr(self._node, 'module'):
            module_str = f'{self._node.module}.'

        return [module_str + name.name for name in self._node.names]

    @property
    def module(self):
        if self.is_imp:
            return self.names

        return self._node.module

    @property
    def local(self):
        return self._src == self.Source_Local

    @property
    def specs(self):
        dlog = self.gen_dlog('spec')

        specs = {}
        for name in self.names:
            spec = SpecWrapper(name)
            # print(spec)
            specs[name] = spec
            # try:
            #     spec = find_spec(name)
            # except AttributeError: # __future__ crashes find_spec lol
            #     dlog(f'name "{name}" raised AttributeError')
            #     continue
            #
            # if spec is None and '.' in name:
            #     # might be a X from Y situation rendered as X.Y, remove a dot and try that as the module
            #     (maybe_module, member) = name.rsplit('.', 1)
            #     dlog(f'Module "{name}" can\'t be found, trying {maybe_module}')
            #     spec = find_spec(maybe_module)
            #     if spec:
            #         name = maybe_module
            #
            # if spec is None:
            #     dlog(f'Module {name} does not appear to be installed in current path.')
            #     # dlog(f'Module {name} does not appear to be installed in current path: {sys.path}')
            # else:
            #     dlog(f'Checking if spec is system spec: {spec}')
            #     if spec.origin and 'site-packages' not in spec.origin:
            #         # builtin case 1
            #         dlog(f'Module "{name}" is not in sitepackages, it is a builtin.')
            #         continue
            #     if spec.loader and spec.loader is BuiltinImporter:
            #         # builtin case 2
            #         dlog(f'Module "{name}" uses the buildin importer.')
            #         continue
            #


        return specs

    def str_with_scope(self):
        return str(self) + f" <- {self._parent}"

    def __str__(self):
        # return f'[{self._node.lineno}|{self._src}]Import {", ".join(self.names)}'
        return f'[{self._node.lineno}]Import {", ".join(self.names)}'

    def __repr__(self):
        return str(self)


class ASTWrapper(Logger):
    # FunctionDef(identifier name, arguments args, stmt * body, expr * decorator_list, expr? returns)
    # | AsyncFunctionDef(identifier name, arguments args, stmt * body, expr * decorator_list, expr? returns)
    # | ClassDef(identifier name, expr * bases, keyword * keywords, stmt * body, expr * decorator_list)
    # | Delete(expr * targets)
    # | Assign(expr * targets, expr value)
    # | For(expr target, expr iter, stmt * body, stmt * orelse)
    # | AsyncFor(expr target, expr iter, stmt * body, stmt * orelse)
    # | While(expr test, stmt * body, stmt * orelse)
    # | If(expr test, stmt * body, stmt * orelse)
    # | With(withitem * items, stmt * body)
    # | AsyncWith(withitem * items, stmt * body)
    # | Try(stmt * body, excepthandler * handlers, stmt * orelse, stmt * finalbody)
    # | List(expr * elts, expr_context ctx)
    # | Tuple(expr * elts, expr_context ctx)
    # | Dict(expr* keys, expr* values)
    # | Set(expr* elts)
    # arguments = (arg * args, arg? vararg, arg * kwonlyargs, expr * kw_defaults, arg? kwarg, expr * defaults)

    _NAME = 'ASTWrapper'

    _NODES_WITH_CHILDREN_TO_KEYS = {
        ast.FunctionDef: ('body',),
        ast.AsyncFunctionDef: ('body',),
        ast.ClassDef: ('body',),
        ast.Delete: ('targets',),
        ast.Assign: ('targets',),
        ast.Module: ('body',),
        ast.For: ('for', 'orelse'),
        ast.AsyncFor: ('for', 'orelse'),
        ast.If: ('body', 'orelse'),
        ast.While: ('body', 'orelse'),
        ast.With: ('withitem', 'body'),
        ast.AsyncWith: ('withitem', 'body'),
        ast.Try: ('body', 'handlers', 'orelse', 'finalbody'),
        ast.List: ('elts',),
        ast.Tuple: ('elts',),
        ast.Dict: ('keys', 'values'),
        ast.Set: ('elts',),
        ast.ExceptHandler: ('body',)
        # arguments
    }

    # FunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
    # | AsyncFunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
    # | ClassDef(identifier name, expr* bases, keyword* keywords, stmt* body, expr* decorator_list)
    # | Assign(expr* targets, expr value)
    # | AugAssign(expr target, operator op, expr value)
    # | AnnAssign(expr target, expr annotation, expr? value, int simple)
    _NODES_THAT_ADD_TO_SYMBOL_TABLE_TO_KEY = {
        ast.Assign: 'targets',
        ast.AugAssign: 'target',
        ast.AnnAssign: 'target',
        ast.FunctionDef: 'name',
        ast.AsyncFunctionDef: 'name',
        ast.ClassDef: 'name'
    }

    # The easy case
    _SYMBOL_BY_ID = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef
    )

    # the harder case
    _SYMBOL_BY_EXPR = (
        ast.Assign,
        ast.AugAssign,
        ast.AnnAssign
    )

    _var_marker = ('{', '}')

    def __init__(self, node: ast.AST, parent: 'ASTWrapper' = None, log_node = False):
        super().__init__()

        self.node = node

        self.parent = parent
        self.log_node = log_node
        self.children = []
        self._imports: List[ImportContext] = []
        self._local_imports = False
        self._first_line = 0
        self._last_line = 0
        self._symbols = {}
        if self._has_line:
            self._first_line = self.line
            self._last_line = self.line

        # self.wlog('_i_', f'{self}')
        if self.has_children:
            # self.wlog('_i_', f'>has children')
            child_keys = self._NODES_WITH_CHILDREN_TO_KEYS[self._n_class]
            for key in child_keys:
                container = getattr(self.node, key, None)
                if container:
                    for element in container:
                        self.children.append(self._make_child_wrapper(element))
                    output = '\n\t' + '\n\t'.join([str(c) for c in self.children])
                    # self.wlog('_i_', f'{self.node.__class__.__name__}[{key}] = {output}')

        self._handle_node_symbol()

        if parent is not None:
            if self._has_line:
                parent._child_line_number(self.node.lineno)
            if self.children: # get list of scope imports
                self._imports.extend(parent._get_scope_imports())

        if self.log_node:
            self.dlog("i",f'{self}')

    def _handle_node_symbol(self):
        if not self._node_adds_symbol or not self.parent:
            return

        # find and add symbols to table
        member_name = self._NODES_THAT_ADD_TO_SYMBOL_TABLE_TO_KEY[self._n_class]
        symbol_member = getattr(self.node, member_name, None)

        if symbol_member is None:
            raise ValueError(f"{self}: expected to find a symbol!")

        values = [self]
        # self.wlog('_i_:node_adds_symbol', f'{self}({symbol_member})')
        if self._n_class in self._SYMBOL_BY_EXPR:
            # Symbol is contained in an expression, that must be resolved first
            symbol_names = self._resolve_expr_symbols(symbol_member)
        else:
            # symbol is contained in an id, which is just a string, so we already have it in symbol_member
            symbol_names = [symbol_member]  # makes the processing easier if it's always a list

        if len(symbol_names) > 0:
            if len(symbol_names) != len(values):
                self.wlog(
                    "_child_adds_symbol",
                    f"{self}:{len(symbol_names)}syms != {len(values)}vals! Symbol table may be flawed!"
                )
            self.parent._child_adds_symbol(symbol_names, values)
        # else:
        #     self.wlog('_handle_node_symbol', f'Skipping add because we generated no symbols')

    def _child_adds_symbol(self, symbol_names: List[str], values: List[Any]) -> None:
        """
        Adds one or more symbols from a child AST node to our table of symbols.
        :param symbol_names: List of identifiers
        :param values: Values for identifiers
        :return: None
        """

        # There is a corner case here that I'm not quite sure what to do with.
        # The easy case is when the number of names and the number of values match:
        #   names:  [a, b, c]
        #   values: [x, y, z]
        #   ->
        #   table {a:x, b:y, c:z}
        # See? Easy
        #
        # It's also possible that multiple values in a tuple are being unpacked:
        #   names:  [a, b, c]
        #   values: [x()]
        #   ->
        #   table {a:x()[0], b:x()[1], c:x()[2]}
        # This has encoding problems, but at least intent is clear
        #
        # But then, what about this:
        #   names:  [[a, b], c]
        #   values: [x()]
        #   -?>
        #   table {a:x()[0][0], b:x()[0][1], c:x()[1]} ???
        #   -?>
        #   table {a:x()[0], b:x()[0][1], c:x()[1]} ???
        # I'm not really sure! It kind of sucks and hopefully we can just ignore the more complicated cases here.
        #  For our purposes ignoring these should be fine because we only care about imports and we won't be able to
        #  detect when a function call triggers an import - that's beyond our scope for now!

        # self.dlog("_child_adds_symbol", f"({symbol_names}, {values})")
        last_value = None
        for name in symbol_names:
            # if counts match, we can just pop them all
            if len(values):
                last_value = values.pop(0)

            # todo: create some kind of index reference!
            self._symbols[name] = last_value

    def _resolve_expr_symbols(self, exprs):
        if not isinstance(exprs, list):
            exprs = [exprs]
        # dig into these exprs and see what's what
        # todo: check that this is working better
        # self.dlog('_resolve_expr_symbols', f'Exprs: {", ".join([self.node_str(e) for e in exprs])}')
        # self.dlog('_resolve_expr_symbols', f'Exprs: {exprs}')
        result = []
        for e in exprs:
            out = []
            if isinstance(e, ast.Name):
                # | Name(identifier id, expr_context ctx)
                out.append(f'{e.id}')
            elif isinstance(e, ast.Attribute):
                # | Attribute(expr value, identifier attr, expr_context ctx)
                # this expects a list
                value_strings = self._resolve_expr_symbols(e.value)
                if not isinstance(value_strings, list) or len(value_strings) != 1:
                    raise Exception(f"This is an unexpected format: {value_strings}")
                out.append(f'{value_strings[0]}.{e.attr}')
            elif isinstance(e, ast.Tuple):
                # | Tuple(expr* elts, expr_context ctx)
                for expr in e.elts:
                    for identifier in self._resolve_expr_symbols(expr):
                        out.append(identifier)
            elif isinstance(e, ast.Subscript):
                # | Subscript(expr value, slice slice, expr_context ctx)
                # This will always be adding a symbol to something that's already in our symbol table and I think we can safely ignore it
                pass
            else:
                self.dlog('_resolve_expr_symbols', f'\tExpr({e})({self.node_str(e)}) does not seem to generate a symbol, skipping')
                continue

            # self.dlog('_resolve_expr_symbols', f'\t{out}')
            result.extend(out)

        return result

    def _make_child_wrapper(self, element):
        wrapper = ASTWrapper(element, self, log_node = self.log_node)
        if ImportContext.node_is_import(element):
            # new import in "our" context
            self._local_imports = True
            self._imports.append(ImportContext(element, self, ImportContext.Source_Local))

        return wrapper

    def _get_scope_imports(self):
        return [i.re_contextualize(ImportContext.Source_Above) for i in self._imports]

    @property
    def has_symbols(self):
        return len(self._symbols) > 0

    @property
    def children_with_children(self):
        return list(filter(lambda x: x.has_children, self.children))

    @property
    def has_local_imports(self):
        return self._local_imports

    @property
    def local_imports(self):
        return list(filter(lambda i: i.local, self._imports))

    @property
    def interesting(self):
        # This is kind of a made up quality (ha! all qualities are made up! Anthropology!)
        # its purpose is to prone any tree nodes that: have no local imports or no links to
        # local imports

        if self.has_local_imports:
            return True # we have locally defined imports so we're important

        for c in self.children:
            if c.interesting:
                return True # if our kids are interesting so are we

        return False

    @property
    def interesting_children(self):
        return list(filter(lambda x: x.interesting, self.children))

    def imports_for_symbol(self, symbol_name: str = None) -> List[ImportContext]:
        symbol = self
        if symbol_name:
            symbol = self._symbols.get(symbol_name, None)

            if symbol is None:
                raise ValueError(f"Looked for symbol {symbol_name}, but found nothing in table: {self._symbols}")

        # selected symbol imports
        imports = list(symbol.local_imports)
        # and all the imports of
        for c in symbol.children:
            imports.extend(c.imports_for_symbol())
        return imports

    def report(self):
        me = f'>{self}'

        imports = ''
        # symbols = ''
        kids_w_kids = ''

        if self.has_local_imports:
            imports = '\n\t' + '\n\t'.join([f'{i}' for i in self.local_imports])

        # if self._symbols:
        #     symbols = '\n*Symbols:\n\t' + '\n\t'.join([f'{i} = {v}' for i, v in self._symbols.items()])

        interesting_kids = [cwc.report().split("\n") for cwc in self.interesting_children]

        if interesting_kids:
            kids_w_kids = '\n\t\\\n\t'
            kids_w_kids += '\n\t'.join(chain.from_iterable(interesting_kids))

        return me + imports + kids_w_kids
        # return me + imports + symbols + kids_w_kids

    @property
    def has_children(self):
        return self._n_class in list(self._NODES_WITH_CHILDREN_TO_KEYS.keys())

    @property
    def _node_adds_symbol(self):
        return self._n_class in list(self._NODES_THAT_ADD_TO_SYMBOL_TABLE_TO_KEY.keys())

    def _child_line_number(self, line_number):
        if self._first_line > line_number:
            self._first_line = line_number
            if self.parent is not None:
                self.parent._child_line_number(self.node.lineno)
        if self._last_line < line_number:
            self._last_line = line_number
            if self.parent is not None:
                self.parent._child_line_number(self.node.lineno)

    @property
    def line(self):
        return getattr(self.node, 'lineno', 0)

    @property
    def _has_line(self):
        return hasattr(self.node, 'lineno')

    @property
    def _n_class(self):
        return getattr(self.node, '__class__', None)

    @property
    def first_line(self):
        return self._first_line

    @property
    def last_line(self):
        return self._last_line

    @property
    def lines(self):
        return self._last_line - self._first_line

    @staticmethod
    def _unwrap_alias(node):
        if not isinstance(node, ast.alias):
            raise ValueError(f"{node} not an alias!")
        return node.name

    @staticmethod
    def _line_number_str(node, ctx: PrintCtx):
        this_line_number = getattr(node, 'lineno', None)
        line_string = ''
        # check for line 0
        # new number
        if this_line_number is not None and ctx.line_number is None:
            ctx.line_number = this_line_number
            ctx.in_statement = True
            line_string = f'[{ctx.line_number}]'
        if (this_line_number is not None and ctx.line_number is not None
            and this_line_number > ctx.line_number
            ):
            ctx.line_number = this_line_number
            line_string = f'[{ctx.line_number}]'
            ctx.in_statement = True
            # after 1st number add a newline
            if ctx.in_statement:
                line_string = "\n\t\t" + line_string

        if (
            this_line_number is not None and ctx.line_number is not None
                and this_line_number < ctx.line_number
            ): # exception time
            raise ValueError(f"Didn't expect line numbers to go backwards: {ctx.line_number}->{this_line_number}")

        return (line_string, ctx)

    @staticmethod
    def _ctx_string(node_ctx_str, ctx: PrintCtx):
        ctx_string = ''
        if ctx.ctx_obj and ctx.ctx_obj != node_ctx_str:
            # new ctx object
            ctx_string = f'[{node_ctx_str}]'
        if not ctx.ctx_obj and node_ctx_str:
            ctx_string = f'[{node_ctx_str}]'
            ctx.ctx_obj = ctx_string

        return (ctx_string, ctx)

    def node_str(self, node, ctx: PrintCtx = None):
        if ctx is None:
            ctx = PrintCtx()
        # mod
        # Module(stmt* body)
        # | Interactive(stmt* body)
        # | Expression(expr body)
        #
        if isinstance(node, ast.Module):
            return 'Module[]'
        # stmts
        # stmt

        #
        #
        # | Delete(expr* targets)
        # | AugAssign(expr target, operator op, expr value)
        # -- 'simple' indicates that we annotate simple name without parens
        # | AnnAssign(expr target, expr annotation, expr? value, int simple)
        #
        # -- use 'orelse' because else is a keyword in target languages
        #
        # | Raise(expr? exc, expr? cause)
        # | Assert(expr test, expr? msg)
        #
        #
        # | Global(identifier* names)
        # | Nonlocal(identifier* names)
        #
        # -- col_offset is the byte offset in the utf8 string the parser uses
        # attributes (int lineno, int col_offset)
        #
        # -- BoolOp() can use left & right?
        elif isinstance(node, ast.FunctionDef):
            # FunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
            # todo: fix
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'{line_str}def {node.name}({self.node_str(node.args, ctx)}):'
        # | AsyncFunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
        elif isinstance(node, ast.AsyncFunctionDef):
            # todo: fix
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'{line_str}async def {node.name}({self.node_str(node.args, ctx)}):'
        elif isinstance(node, ast.ClassDef):
            # | ClassDef(identifier name, expr* bases, keyword* keywords, stmt* body, expr* decorator_list)
            (line_str, ctx) = self._line_number_str(node, ctx)
            bases = ', '.join([self.node_str(base, ctx) for base in node.bases])
            if node.keywords:
                print(f'Class keywords: {node.keywords}')
            if node.decorator_list:
                print(f'Class decorator list: {node.decorator_list}')
            return f'{line_str}class {node.name}({bases}):'
        elif isinstance(node, ast.Return):
            # | Return(expr? value)
            return f'return {self.node_str(node.value, ctx)}'
        elif isinstance(node, ast.Try):
            # | Try(stmt* body, excepthandler* handlers, stmt* orelse, stmt* finalbody)
            # todo: make this better?
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'{line_str}Try:'
        elif isinstance(node, ast.Expr):
            # | Expr(expr value)
            # return f'Expr({self.node_str(node.value)})'
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'{line_str}{self.node_str(node.value, ctx)}'
        elif isinstance(node, ast.Assign):
            # | Assign(expr* targets, expr value)
            (line_str, ctx) = self._line_number_str(node, ctx)

            return '{}{} = {}'.format(
                line_str,
                ', '.join([self.node_str(t, ctx) for t in node.targets]),
                self.node_str(node.value, ctx)
            )

        elif isinstance(node, ast.AugAssign):
            # | AugAssign(expr target, operator op, expr value)
            (line_str, ctx) = self._line_number_str(node, ctx)

            return f'{line_str} {self.node_str(node.target, ctx)} {self.node_str(node.op)} {self.node_str(node.value)}'
        elif isinstance(node, ast.Import):
            # | Import(alias* names)
            names = [self._unwrap_alias(n) for n in node.names]
            (line_str, ctx) = self._line_number_str(node, ctx)

            return f'{line_str}Import {", ".join(names)}'
        elif isinstance(node, ast.ImportFrom):
            # | ImportFrom(identifier? module, alias* names, int? level)
            names = [self._unwrap_alias(n) for n in node.names]
            mod = getattr(node, 'module', "Unknown")
            (line_str, ctx) = self._line_number_str(node, ctx)

            return f'{line_str}From {mod} import {", ".join(names)}'
        elif isinstance(node, ast.For):
            # | For(expr target, expr iter, stmt* body, stmt* orelse)
            (line_str, ctx) = self._line_number_str(node, ctx)

            target_str = self.node_str(node.target, ctx)
            iter_str = self.node_str(node.iter, ctx)
            body_str = "\n\t\t".join([self.node_str(s, ctx) for s in node.body])
            else_str = ''
            if node.orelse:
                else_str = 'else:\n\t\t{}'.format("\n\t\t".join([self.node_str(s, ctx) for s in node.orelse]),)

            return '{}For {}, {}\n\t\t'.format(
                line_str,
                target_str, iter_str,
                    body_str,
                    else_str
            )

        # | AsyncFor(expr target, expr iter, stmt* body, stmt* orelse)
        # | While(expr test, stmt* body, stmt* orelse)
        elif isinstance(node, ast.If):
            # | If(expr test, stmt* body, stmt* orelse)
            (line_str, ctx) = self._line_number_str(node, ctx)

            test_str = self.node_str(node.test, ctx)
            body_str = "\n\t\t".join([self.node_str(s, ctx) for s in node.body])
            else_str = ''
            if node.orelse:
                else_str = 'else:\n\t\t{}'.format("\n\t\t".join([self.node_str(s, ctx) for s in node.orelse]),)

            return '{}If {}:\n\t\t'.format(
                line_str,
                test_str,
                    body_str,
                    else_str
            )

        # | With(withitem* items, stmt* body)
        # | AsyncWith(withitem* items, stmt* body)
        # | Pass | Break | Continue
        elif isinstance(node, ast.Pass):
            return 'Pass'
        elif isinstance(node, ast.Break):
            return 'Break'
        elif isinstance(node, ast.Continue):
            return 'Continue'
        # expr
        # | Dict(expr* keys, expr* values)
        # | Set(expr* elts)
        # | ListComp(expr elt, comprehension* generators)
        # | SetComp(expr elt, comprehension* generators)
        # | DictComp(expr key, expr value, comprehension* generators)
        # | GeneratorExp(expr elt, comprehension* generators)
        # -- the grammar constrains where yield expressions can occur
        # | Await(expr value)
        # | Yield(expr? value)
        # | YieldFrom(expr value)
        # -- need sequences for compare to distinguish between
        # -- x < 4 < 3 and (x < 4) < 3

        # | FormattedValue(expr value, int? conversion, expr? format_spec)
        # | JoinedStr(expr* values)
        # | Bytes(bytes s)
        # | Ellipsis
        # | Constant(constant value)
        #
        # -- the following expression can appear in assignment context
        # | Starred(expr value, expr_context ctx)
        #
        # -- col_offset is the byte offset in the utf8 string the parser uses
        # attributes (int lineno, int col_offset)
        elif isinstance(node, ast.BoolOp):
            # BoolOp(boolop op, expr* values)
            # print(f"boolop: values:{node.values}, op: {node.op}")
            (line_str, ctx) = self._line_number_str(node, ctx)
            return ' '.join([
                line_str,
                self.node_str(node.values[0], ctx),
                self.node_str(node.op, ctx),
                self.node_str(node.values[1], ctx)
            ])

        elif isinstance(node, ast.UnaryOp):
            # | UnaryOp(unaryop op, expr operand)
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'{line_str}{self.node_str(node.op, ctx)}{self.node_str(node.operand, ctx)}'
        elif isinstance(node, ast.Call):
            # | Call(expr func, expr* args, keyword* keywords)
            (line_str, ctx) = self._line_number_str(node, ctx)
            return ''.join([
                line_str, self.node_str(node.func, ctx),
                '(',
                    f'{", ".join([self.node_str(a, ctx) for a in node.args])}',
                    f'{", ".join([self.node_str(a, ctx) for a in node.keywords])}',
                ')'
            ])
        elif isinstance(node, ast.Lambda):
            # | Lambda(arguments args, expr body)
            return f'lambda {self.node_str(node.args, ctx)}: {self.node_str(node.body, ctx)}'
        elif isinstance(node, ast.IfExp):
            # | IfExp(expr test, expr body, expr orelse)
            return f'{self.node_str(node.body, ctx)} If {self.node_str(node.test, ctx)} else {self.node_str(node.orelse, ctx)}'

        elif isinstance(node, ast.Num):
            # | Num(object n) -- a number as a PyObject.
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'#{line_str}{node.n}' # use objects tostring
        elif isinstance(node, ast.NameConstant):
            # true, false
            return f'{node.value}'
        # | NameConstant(singleton value)
        elif isinstance(node, ast.Compare):
            # | Compare(expr left, cmpop* ops, expr* comparators)
            (line_str, ctx) = self._line_number_str(node, ctx)
            ops = node.ops
            comparators = node.comparators
            result = f'{line_str}{self.node_str(node.left, ctx)}'
            while ops:
                this_op = ops.pop(0)
                this_comp = comparators.pop(0)
                result += f' {self.node_str(this_op, ctx)} {self.node_str(this_comp, ctx)}'

            return result
        elif isinstance(node, ast.Name):
            # | Name(identifier id, expr_context ctx)
            (ctx_str, ctx) = self._ctx_string(self.node_str(node.ctx, ctx), ctx)
            return f'{ctx_str}{self._var_marker[0]}{node.id}{self._var_marker[1]}'
        elif isinstance(node, ast.BinOp):
            # | BinOp(expr left, operator op, expr right)
            return f'{self.node_str(node.left, ctx)} {self.node_str(node.op, ctx)} {self.node_str(node.right, ctx)}'
        elif isinstance(node, ast.Str):
            # | Str(string s) -- need to specify raw, unicode, etc?
            if ctx.in_statement:
                return f"'{node.s}'"
            else:
                lines = node.s.split("\n")
                return '\n"' + "\n".join(lines) + '"'
            # return self.node_str(node.s)
        elif isinstance(node, ast.Attribute):
            # | Attribute(expr value, identifier attr, expr_context ctx)
            (line_str, ctx) = self._line_number_str(node, ctx)
            (ctx_str, ctx) = self._ctx_string(self.node_str(node.ctx, ctx), ctx)
            return f'{line_str}{ctx_str}{self.node_str(node.value, ctx)}.{self._var_marker[0]}{node.attr}{self._var_marker[1]}'
            # return f'Attribute[{node.lineno}](value:{self.node_str(node.value)}, attr:{node.attr}, ctx:{self.node_str(node.ctx)})'
        elif isinstance(node, ast.Tuple):
            # | Tuple(expr* elts, expr_context ctx)
            (line_str, ctx) = self._line_number_str(node, ctx)
            (ctx_str, ctx) = self._ctx_string(self.node_str(node.ctx, ctx), ctx)
            return f'{line_str}{ctx_str}({", ".join([self.node_str(e, ctx) for e in node.elts])})'
        elif isinstance(node, ast.List):
            # | List(expr* elts, expr_context ctx)
            (line_str, ctx) = self._line_number_str(node, ctx)
            (ctx_str, ctx) = self._ctx_string(self.node_str(node.ctx, ctx), ctx)
            return f'{line_str}{ctx_str}[{", ".join([self.node_str(e, ctx) for e in node.elts])}]'
        elif isinstance(node, ast.Subscript):
            # | Subscript(expr value, slice slice, expr_context ctx)
            (line_str, ctx) = self._line_number_str(node, ctx)
            (ctx_str, ctx) = self._ctx_string(self.node_str(node.ctx, ctx), ctx)
            return f'{line_str}{ctx_str}{self.node_str(node.value)}{self.node_str(node.slice)}'

        elif isinstance(node, ast.keyword):
            # keyword = (identifier? arg, expr value)
            (line_str, ctx) = self._line_number_str(node, ctx)
            return f'{line_str}{self._var_marker[0]}{node.arg}{self._var_marker[1]}={self.node_str(node.value, ctx)}'
        # arguments
        elif isinstance(node, ast.arguments):
            # arguments = (arg* args, arg? vararg, arg* kwonlyargs, expr* kw_defaults, arg? kwarg, expr* defaults)
            # todo: I don't understand this
            formatted_args = []
            args = deepcopy(node.args)
            defaults = deepcopy(node.defaults)
            while len(args):
                this_arg = args.pop(0)
                this_default = None

                def_str = ''
                if len(args) < len(defaults):
                    this_default = defaults.pop(0)
                    def_str = f'={self.node_str(this_default, ctx)}'

                formatted_args.append(
                    f'{self.node_str(this_arg, ctx)}{def_str}'
                )

                # args = ', '.join([self.node_str(arg, ctx) for arg in node.args])
            if node.vararg:
                # print(f'vararg: {node.vararg}')
                formatted_args.append(f'*{self.node_str(node.vararg, ctx)}')
            if node.kwarg:
                # print(f'kwarg: {node.kwarg}')
                formatted_args.append(f'**{self.node_str(node.kwarg, ctx)}')
            if node.kwonlyargs:
                print(f'kwonly: {node.kwonlyargs}')
            if node.kw_defaults:
                print(f'kwdefs: {node.kw_defaults}')

            # if node.defaults:
            #     print(f'defaults: {[self.node_str(d, ctx) for d in node.defaults]}')

            return ', '.join(formatted_args)
        elif isinstance(node, ast.Slice):
            # slice = Slice(expr? lower, expr? upper, expr? step)
            pieces = []
            if node.lower:
                pieces.append(self.node_str(node.lower))
            if node.upper:
                pieces.append(self.node_str(node.upper))
            if node.step:
                pieces.append(self.node_str(node.step))
            return f'[{":".join(pieces)}]'
        elif isinstance(node, ast.ExtSlice):
            # | ExtSlice(slice * dims)
            # todo fix?
            return f'!EXT SLICE'
        elif isinstance(node, ast.Index):
            # | Index(expr value)
            return f'{self.node_str(node.value, ctx)}'
        elif isinstance(node, ast.ExceptHandler):
            # excepthandler = ExceptHandler(expr? type, identifier? name, stmt * body)
            # attributes(int lineno, int col_offset)
            type = ''
            name = ''
            if node.type:
                type = f' {self.node_str(node.type, ctx)}'
            if node.name:
                name = f' {name}'
            return f'except{type}{name}:'
        # unary op
        # unaryop = Invert | Not | UAdd | USub
        elif isinstance(node, ast.Invert):
            # todo: what is this?
            return "-"
        elif isinstance(node, ast.Not):
            return "not "
        elif isinstance(node, ast.UAdd):
            # todo: check
            return "+= "
        elif isinstance(node, ast.USub):
            # todo: check
            return "-= "
        # bool ops
        elif isinstance(node, ast.arg):
            # arg = (identifier arg, expr? annotation)
            # attributes (int lineno, int col_offset)
            # ignore annotation

            return f'{self._var_marker[0]}{node.arg}{self._var_marker[1]}'

        elif isinstance(node, ast.And):
            return "and"
        elif isinstance(node, ast.Or):
            return "or"
        # cmpop = Eq | NotEq | Lt | LtE | Gt | GtE | Is | IsNot | In | NotIn
        elif isinstance(node, ast.Eq):
            return "=="
        elif isinstance(node, ast.NotEq):
            return "!="
        elif isinstance(node, ast.Lt):
            return "<"
        elif isinstance(node, ast.LtE):
            return "<="
        elif isinstance(node, ast.Gt):
            return ">"
        elif isinstance(node, ast.GtE):
            return ">="
        elif isinstance(node, ast.Is):
            return "is"
        elif isinstance(node, ast.IsNot):
            return "is not"
        elif isinstance(node, ast.In):
            return "in"
        elif isinstance(node, ast.NotIn):
            return "not in"
        # operators
        elif isinstance(node, ast.Add):
            # return 'Add'
            return '+'
        elif isinstance(node, ast.Sub):
            # return 'Sub'
            return '-'
        elif isinstance(node, ast.Mult):
            # return 'Mult'
            return '*'
        elif isinstance(node, ast.Div):
            # return 'Div'
            return '/'
        elif isinstance(node, ast.Mod):
            # return 'Mod'
            return '%'
        elif isinstance(node, ast.Pow):
            # return 'Pow'
            return '^'
        elif isinstance(node, ast.LShift):
            # return 'LShift'
            return '<<'
        elif isinstance(node, ast.RShift):
            # return 'RShift'
            return '>>'
        elif isinstance(node, ast.BitOr):
            # return 'BitOr'
            return '|'
        elif isinstance(node, ast.BitXor):
            return '^='
        elif isinstance(node, ast.BitAnd):
            return '&'
        elif isinstance(node, ast.FloorDiv):
            return '//'
        # contexts
        elif isinstance(node, ast.Load):
            # return 'Load'
            return 'L'
        elif isinstance(node, ast.Store):
            # return 'Store'
            return 'S'
        elif isinstance(node, ast.Del):
            # return 'Del'
            return 'D'
        elif isinstance(node, ast.AugLoad):
            return 'AugLoad'
        elif isinstance(node, ast.AugStore):
            return 'AugStore'
        elif isinstance(node, ast.Param):
            return 'Param'
        # catches
        elif node is None:
            return 'None'
        elif isinstance(node, str):
            raise Exception()
        else:
            return f'{{!Need code to print: {node}}}'

    def __str__(self):
        return self.node_str(self.node)

    def __repr__(self):
        return self.node_str(self.node)





# class ASTWalker(ast.NodeVisitor):
#     def _visit_single_node(self, value):
#         if isinstance(value, list):
#             for item in value:
#                 if isinstance(item, ast.AST):
#                     self.visit(item)
#         elif isinstance(value, ast.AST):
#             self.visit(value)
#
#     # mods
#     def visit_Module(self, node):
#         # do something with the file name
#         pass
#         # print(f'module: {node}')
#         self.generic_visit(node)
#
#     #expr
#     def visit_ImportFrom(self, imp_from):
#         # module, names (alias)
#         canon_names = [n.name for n in imp_from.names]
#         print(f'ImportFrom[{imp_from.lineno}]: {imp_from.module}:{canon_names}')
#         # print(f'{imp_from._fields}')
#
#     def visit_Import(self, imp):
#         canon_names = [n.name for n in imp.names]
#         print(f'Import[{imp.lineno}]: {canon_names}')
#
#     def visit_Expr(self, expr):
#         self.visit(expr.value)
#         pass
#
#     def visit_Call(self, call_node):
#         pass
#
#     def visit_FunctionDef(self, function_node):
#         # FunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
#         self.generic_visit(function_node.body)
#
#
#     #stmts
#     # a = b
#     def visit_Assign(self, assign):
#         pass
#
#     def visit_Str(self, string):
#         lines = string.s.split("\n")
#         info = "\t" + "\n\t".join(lines)
#         print(f'String: "{info}"')
#
#     def visit_If(self, if_node):
#         self._visit_single_node(if_node.body)
#
#     # expr_context statements that track where in a statement something is
#     # i.e. a = list[store]
#     def visit_Load(self, load_node):
#         pass
#     def visit_Store(self, store_node):
#         pass
#     def visit_Del(self, del_node):
#         pass
#     def visit_AugLoad(self, augload_node):
#         pass
#     def visit_AugStore(self, augstore_node):
#         pass
#     def visit_Param(self, param_node):
#         pass
#
#     def generic_visit(self, node):
#         print(node.__class__.__name__)
#         ast.NodeVisitor.generic_visit(self, node)

class PathWrapper(str):

    @property
    def python_file(self):
        return splitext(self)[1] in ['.py', '.pyc']

class ModuleListingWrapper(Logger):
    _NAME = 'ModuleListingWrapper'

    def __init__(self, value_dict, **kwargs):
        super().__init__(**kwargs)
        # strings
        self.imports: List[ImportContext]  = value_dict.get('imports', [])
        # strings
        self.imported_by: List[str] = value_dict.get('imported_by', [])
        self.name: str = value_dict.get('name')
        self.error: str = value_dict.get('error', None)
        self.path = None

        path = value_dict.get('path', None)
        if path is None and not self.error:
            self.elog('__init__', f'Path is None! args:{value_dict}')

        # if self.error is not None:
        #     self.wlog("__init__", f'{self.name}[ERROR] -> {self.error}')

        if path:
            self.path: PathWrapper = PathWrapper(path)

        # wrappers
        self.children: List[ModuleListingWrapper] = []

        self.implicit = False
        for imp in self.imported_by:
            # TODO: Check if this is correct
            '''
            So this is the plan here:
            If you import X.Y, Python needs to import X as well. This is (I think) because module imports have side
            effects. But the important thing to note is that module X doesn't get pulled into scope (I think). It's just
            module X.Y. So - we try to use this flag
            '''
            if self._is_submodule(imp):
                self.implicit = True

        # self.dlog('__init__', f'Creating {self.name}({id(self)})!')

    def fetch_imports(self):
        self.dlog("fetch_imports", f"({self.path})")
        if self.error:
            self.wlog("fetch_imports", f'\t-Skipping imports for {self.name} because of error: "{self.error}".')
            return

        if not self.path:
            self.wlog("fetch_imports", f'\t-Skipping imports for {self.name} path is none.')
            return

        print(f'{self} - {self.path}({type(self.path)})')
        with open(self.path, "rt") as file:
            st: ast.AST = ast.parse(file.read(), filename=self.path)
            wrap = ASTWrapper(st)
            self.imports = wrap.imports_for_symbol()
            self.dlog("fetch_imports", "->[\n\t{}\n\t]".format(
                '\n\t'.join([str(i) for i in self.imports])
            ))


    @property
    def import_names(self):
        return [name for i in self.imports for name in i.names]

    @property
    def is_imported(self):
        return len(self.imported_by) > 0

    @property
    def decendant_count(self):
        count = len(self.children)
        for c in self.children:
            try:
                count += c.decendant_count
            except RecursionError as re:
                print(f'decendant_count:{self.name}[{self.path}] - Recursion error on child: {c.name}[{c.path}]!')
                raise

        return count

    @property
    def temporary(self):
        return self.name == "__main__"

    def update_children(self, new_child):
        # update any references
        self.children = [
            new_child if new_child.name == c.name else c for c in self.children
        ]

    def get_children(self):
        # gets a flattened list
        children = set(self.children)
        for c in self.children:
            try:
                children.update(c.get_children())
            except RecursionError as re:
                print(f'get_children:{self.short_str()} - Recursion error on child: {c.short_str()}!')
                raise

        return children

    def print_children(self, level = 0):
        if level == 0:
            print(f'{self.short_str()}')
        else:
            spacers =  '     ' * (level - 1) + '|--'
            print(f'{spacers}> {self.short_str()}')

        for c in self.children[:-1]:
            c.print_children(level = level + 1)

        if len(self.children) >= 1:
            self.children[-1].print_children(level=level + 1)

    def _is_submodule(self, name: str):
        return name.startswith(self.name)

    def _str_comps(self, short=False):
        path = self.path or 'X'
        imports = ''
        import_by = ''
        impl = ''
        temp = ''
        if self.implicit:
            impl = '(IMPL)'
        if self.imports:
            if short:
                imports = f'I<{len(self.imports)}'
            else:
                imports = f'I<{self.imports}'
        if self.is_imported:
            if short:
                import_by = f'|(I)>{len(self.imported_by)}'
            else:
                import_by = f'|(I)>{self.imported_by}'
        if self.temporary:
            temp = 'T|'

        return {
            'id': id(self),
            'path': path,
            'imports': imports,
            'import_by': import_by,
            'impl': impl,
            'temp': temp
        }

    def short_str(self):
        components = self._str_comps(short=True)
        return ''.join([
            '[',
            f'{components["temp"]}({self.decendant_count})',
            f'{self.name}{components["impl"]}',
            '|',
                f'{components["path"]}] {components["imports"]}{components["import_by"]}'
        ])

    def __str__(self):
        components = self._str_comps()
        return ''.join([
            '[',
                f'{components["temp"]}({self.decendant_count})',
                f'{self.name}{components["impl"]}',
                    '|',
                    f'{components["path"]}] {components["imports"]}{components["import_by"]}'
            ])

    def __repr__(self):
        return str(self)

class ModuleCrawler(Logger):

    _NAME = 'ModuleCrawler'

    # to get all libraries
    # '--pylib-all', '--pylib'
    ARGS = ['--no-config', '--noshow']

    _ROOT_MODULE = '__main__'

    _Cleanup_Filters = [
        # find any _dummy files
        lambda x: x.startswith('_dummy') and x.endswith('.py')
    ]

    def __init__(self, target: str, **kwargs):
        super().__init__(**kwargs)

        self.has_new_results: bool = False
        self.module_map: Dict[str, ModuleListingWrapper] = {}
        self.path_map: Dict[str, ModuleListingWrapper] = {}
        self.paths_checked: Set[str] = set()
        self.modules_checked: Set[str] = set()
        self.next_paths: Set[str] = {target}

    @property
    def done(self):
        return len(self.next_paths) == 0

    def step(self):
        if not self.has_new_results:
            # do the thing
            target = self.next_paths.pop()
            self._generate_modules_for_target(target)
            self._check_modules_for_one_target(target)
            # cleanup
            self._cleanup()
            self.has_results = True

    def find_roots(self):
        # set of module objects
        mods: Set[ModuleListingWrapper] = set([v for v in self.module_map.values()])
        while len(mods) > 0:
            highest = sorted(mods, reverse=True, key=lambda x: x.decendant_count)[0]
            to_remove = highest.get_children()
            if not highest.temporary:
                print("Root:")
                highest.print_children()

            # gotta add the one we just printed
            to_remove.add(highest)
            mods = mods - to_remove


    # def _make_args(self, target):
    #     a = [target] # have a path to keep arg parse happy
    #     # use class args
    #     a.extend(self.ARGS)
    #     a = pydeps.cli.parse_args(a)
    #     # get rid of name because we're going to use the target object
    #     a.pop('fname')
    #     return a

    # def _call_py2deps(self, target):
    #     dlog = self.gen_dlog('_call_py2deps')
    #     # wlog = self.gen_wlog('_call_py2deps')
    #
    #     dlog(f"Calling py2deps on {target}")
    #     raw_results = py2dep(Target(target), **self._make_args(target))
    #
    #     # turn into my structure
    #     # todo: this isn't actually correct but it's very easy
    #     return {
    #         'root': {self._ROOT_MODULE},
    #         'modules': json.loads(repr(raw_results))
    #     }


    # def _find_imports_in_file(self, path):
    #     self.dlog("_find_imports_in_file", f"({path})")
    #     with open(path, "rt") as file:
    #         st: ast.AST = ast.parse(file.read(), filename=path)
    #         wrap = ASTWrapper(st)
    #         return wrap.imports_for_symbol()

    def _call_findimports(self, target):
        dlog = self.gen_dlog('_call_findimports')

        dlog(f"Calling find_imports on {target}")

        result = {}
        key = None

        if target in self.path_map:
            item = self.path_map[target]
            key = item.name
            if not item.imports:
                item.fetch_imports()

            result[key] = item
        else:
            mg = ModuleGraph()
            mg.parseFile(target)


            key = next(iter(mg.modules.keys()))
            base_module = mg.modules[key]

            # def __init__(self, value_dict, **kwargs):
            #     super().__init__(**kwargs)
            #     # strings
            #     self.imports: List[str] = value_dict.get('imports', [])
            #     # strings
            #     self.imported_by: List[str] = value_dict.get('imported_by', [])
            #     self.name: str = value_dict.get('name')
            #     self.error: str = value_dict.get('error', None)
            #     path = value_dict.get('path', None)
            #     if path is None and not self.error:
            #         self.elog('__init__', f'Path is None! args:{value_dict}')
            #     if self.error is not None:
            #         self.wlog("__init__", f'{self.name}: {self.error}')
            #
            #     self.path: PathWrapper = PathWrapper(path)
            #
            #     # wrappers
            #     self.children: List[ModuleListingWrapper] = []
            #
            #     self.implicit = False

            # imps = self._find_imports_in_file(target)
            module_info = {
                'name': base_module.modname,
                # base_module.imports should include the proper list, but it doesn't - it includes absolutes
                # https://stackoverflow.com/questions/952914/how-to-make-a-flat-list-out-of-list-of-lists
                # this is actually 99% impossible to read but it is proper python lol
                # for i in imps, for each name in i.names, add name to list
                # 'imports': [name for i in imps for name in i.names],
                'error': None,
                'path': target,
                'imported_by': []
            }
            result[key] = ModuleListingWrapper(module_info)
            result[key].fetch_imports()
        # result[key] = {
        #     'name': base_module.modname,
        #     # base_module.imports should include the proper list, but it doesn't - it includes absolutes
        #     # https://stackoverflow.com/questions/952914/how-to-make-a-flat-list-out-of-list-of-lists
        #     # this is actually 99% impossible to read but it is proper python lol
        #     # for i in imps, for each name in i.names, add name to list
        #     'imports': [name for i in imps for name in i.names],
        #     'error': None,
        #     'path': target,
        #     'imported_by': []
        # }

        for i in result[key].imports:
            print(i)
            for full_path, spec in i.specs.items():

                # this will be
                imp_mod_info = {
                    'impored_by': [],
                    'error': spec.error,
                    'name': spec.name,
                    'path': spec.origin or None
                }
                if spec.name not in result:
                    result[spec.name] = ModuleListingWrapper(imp_mod_info)
                    result[spec.name].fetch_imports()

                # we can load it
                # if spec.origin and not spec.error:
                #     # grab he imports
                #     imports = self._find_imports_in_file(spec.origin)
                #
                # result[name] = {
                #     'imports': [name for i in imports for name in i.names],
                #     'impored_by': [],
                #     'error': spec.error,
                #     'name': name,
                #     'path': spec.origin or None
                # }
                # print(result[name])

        return {
            'root': {key},
            'modules': result
        }

    def _generate_modules_for_target(self, target):
        dlog = self.gen_dlog('_gen_mods_for_n_target')
        wlog = self.gen_wlog('_gen_mods_for_n_target')

        # target = self.next_paths.pop()

        raw_modules = self._call_findimports(target)
        # print(raw_modules)

        # bookkeeping
        # todo: do this somewhere else?
        self.paths_checked.add(target)

        for key, val in raw_modules['modules'].items():
            # w = ModuleListingWrapper(val) # no need, did in previous step now
            w = val

            if key in self.module_map and not w.temporary:  # already exists, or replace previous temp module
                # Sometimes replace modules we'e already seen under certain conditions
                # todo: check if this should still happen
                if w.path == target:
                    '''
                    py2dep notices more dependencies when you crawl the file specifically. This is fine because we add
                    secondary requirements to the file list after we scan the first file, but we need to update the module
                    map and also update any existing chilren!
                    '''
                    wlog(f"\tUpdating {self.module_map[key].short_str()} -> {w.short_str()}")
                    self.module_map[key] = w
                    for v in self.module_map.values():
                        v.update_children(w)
                else:
                    wlog(f"\tNot saving <{w.short_str()}>")
            else:
                dlog(f"\tAdding '{key}' to module_map")
                self.module_map[key] = w
                if w.path:
                    self.path_map[w.path] = w

        return raw_modules['root']

    def _check_modules_for_one_target(self, target):
        dlog = self.gen_dlog('_call_py2dep')
        wlog = self.gen_wlog('_call_py2dep')

        modules_checked = set()
        # modules = {self._ROOT_MODULE}  # generally a stub file created by py2dep

        current_module = self.path_map.get(target)

        # don't repeat these either
        modules_checked.add(current_module.name)
        if current_module.error:
            wlog(f'Skipping <{current_module.name}>: {current_module.error}')
        else:
            wlog(f'Checking <{current_module.name}>')

            # remember to itterate over names here
            for imp in current_module.import_names:
                if imp not in self.module_map:
                    wlog(f'\tModule "{imp}" not found in module map!')
                    continue
                import_module = self.module_map[imp]


                if import_module.error:
                    wlog(f'\t-Not checking <{import_module.name}> - Error: {import_module.error}')
                    continue
                # don't inspect the imports of implicit modules


                if import_module.name not in modules_checked:
                    if not import_module.implicit:
                        # wlog(f'\t+Adding <{import_module.name}> to list of imports to check')
                        # modules.add(import_module.name)
                        # otherwise
                        if not current_module.temporary:
                            wlog(f'\t\t+Adding {import_module.short_str()} to children of {current_module.short_str()}')
                            current_module.children.append(import_module)
                    else:
                        wlog(f'\t-Not checking imports of <{import_module.name}> - Implicit')
                else:
                    wlog(f'\t-Not checking imports of <{import_module.name}> - Already checked')


                if import_module.path and import_module.path.python_file and\
                        import_module.path not in self.paths_checked:
                    # don't double-check paths
                    if not import_module.implicit:
                        wlog(f'\t++Adding [{import_module.path}] to [FILES]')
                        self.next_paths.add(import_module.path)
                    else:
                        wlog(f'\t--Not adding [{import_module.path}] to [FILES]: Implicit import')
                else:
                    reason = 'Already crawled'
                    if import_module.path is None:
                        reason = f'Path is None: {import_module}'
                    elif not import_module.path.python_file:
                        reason =f'Not a python file: {import_module}'
                    wlog(f'\t--Not adding [{import_module.path}] to [FILES]: {reason}')


        wlog(f'Round Complete!')
        wlog(f'\tProcessed: {current_module}')
        # wlog(f'\t<modules>:{modules}')
        formatted_paths = ""
        # print(self.next_paths)
        if self.next_paths:
            formatted_paths = "\n\t".join([p for p in self.next_paths])
        wlog(f'\t[FILES]:{formatted_paths}')
        all_modules = ""
        if self.module_map:
            all_modules ="[\n\t\t" +  "\n\t\t".join([f"{v.short_str()}" for v in self.module_map.values()]) +"\n]"
        wlog(f'\tAll Modules: {all_modules}')

    # def _check_modules_for_one_target(self, modules):
    #     dlog = self.gen_dlog('_call_py2dep')
    #     wlog = self.gen_wlog('_call_py2dep')
    #
    #     modules_checked = set()
    #     # modules = {self._ROOT_MODULE}  # generally a stub file created by py2dep
    #     while len(modules) > 0:
    #         module_name = modules.pop()
    #         current_module = self.module_map.get(module_name)
    #
    #         # don't repeat these either
    #         modules_checked.add(current_module.name)
    #         if current_module.error:
    #             wlog(f'Skipping <{current_module.name}>: {current_module.error}')
    #             continue
    #
    #         wlog(f'Checking <{current_module.name}>')
    #
    #         # remember to itterate over names here
    #         for imp in current_module.import_names:
    #             if imp not in self.module_map:
    #                 wlog(f'\tModule "{imp}" not found in module map!')
    #                 continue
    #             import_module = self.module_map[imp]
    #
    #
    #             if import_module.error:
    #                 wlog(f'\t-Not checking <{import_module.name}> - Error: {import_module.error}')
    #                 continue
    #             # don't inspect the imports of implicit modules
    #
    #
    #             if import_module.name not in modules_checked:
    #                 if not import_module.implicit:
    #                     # wlog(f'\t+Adding <{import_module.name}> to list of imports to check')
    #                     # modules.add(import_module.name)
    #                     # otherwise
    #                     if not current_module.temporary:
    #                         wlog(f'\t\t+Adding {import_module.short_str()} to children of {current_module.short_str()}')
    #                         current_module.children.append(import_module)
    #                 else:
    #                     wlog(f'\t-Not checking imports of <{import_module.name}> - Implicit')
    #             else:
    #                 wlog(f'\t-Not checking imports of <{import_module.name}> - Already checked')
    #
    #
    #             if  import_module.path and import_module.path.python_file and\
    #                     import_module.path not in self.paths_checked:
    #                 # don't double-check paths
    #                 if not import_module.implicit:
    #                     wlog(f'\t++Adding [{import_module.path}] to [FILES]')
    #                     self.next_paths.add(import_module.path)
    #                 else:
    #                     wlog(f'\t--Not adding [{import_module.path}] to [FILES]: Implicit import')
    #             else:
    #                 reason = 'Already crawled'
    #                 if import_module.path is None:
    #                     reason = f'Path is None: {import_module}'
    #                 elif not import_module.path.python_file:
    #                     reason =f'Not a python file: {import_module}'
    #                 wlog(f'\t--Not adding [{import_module.path}] to [FILES]: {reason}')
    #
    #
    #         wlog(f'Round Complete!')
    #         wlog(f'\tProcessed: {current_module}')
    #         wlog(f'\t<modules>:{modules}')
    #         formatted_paths = ""
    #         # print(self.next_paths)
    #         if self.next_paths:
    #             formatted_paths = "\n\t".join([p for p in self.next_paths])
    #         wlog(f'\t[FILES]:{formatted_paths}')
    #         all_modules = ""
    #         # if self.module_map:
    #         #     all_modules ="[\n\t\t" +  "\n\t\t".join([f"{v.short_str()}" for v in self.module_map.values()]) +"\n]"
    #         # wlog(f'\tAll Modules: {all_modules}')

    def _cleanup(self):
        base = getcwd()
        files = listdir(base)
        for f in ModuleCrawler._Cleanup_Filters:
            files = filter(f, files)

        for f in files:
            # remove files from filters
            remove(join(base, f))
