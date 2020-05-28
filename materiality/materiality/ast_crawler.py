import ast

from importlib.util import find_spec
from importlib.machinery import BuiltinImporter
from copy import deepcopy, copy
from typing import Set, List, Optional, Dict, Any

from .utils import Logger, PythonPathWrapper

_Common_Exception = "find_spec raised a"


class ImportReference(Logger):
    """
    Helper object to track what an import refers _to_ - which module (and what file),
    which symbols in that module. Not tied to a particular file - a given Import X statement
    is the same as any other.
    """

    _NAME = "ImportReference"

    # todo: This class is 'working' if it finds a path for the import
    # todo: but currently, this is not how errors are set. If we can't find
    # todo: the spec we should be setting the NOT_FOUND error, but I forgot
    # todo: to do this and it's why the class works at all.
    # todo: I should go back and sort out the internal logic to be focused on
    # todo: finding the spec as one way to discover the path
    # normal errors
    NOT_FOUND = "Module Not Found"
    SYSTEM_LIBRARY = "System Module"
    RELATIVE = "Relative Import"
    # exceptions
    EXCEPTION = _Common_Exception
    ATTRIBUTE_EXCEPTION = f"{_Common_Exception}n AttributeError"
    MODULE_NOT_FOUND_EXCEPTION = f"{_Common_Exception}ModuleNotFoumdError"
    VALUE_EXCEPTION = f'{_Common_Exception}ValueError'

    def __init__(self, statement_file_path : str, module : str, symbols : List[str] = None, level : int = 0, **kwargs):
        super().__init__(**kwargs)

        self.statement_file_path = statement_file_path
        # canonical module name
        self.module = module
        # canonical list of symbols imported from module
        self.symbols = symbols
        # spec object - MAY BE IGNORED - only finds modules on path
        self.spec = None
        self.ignore_reason = None
        # path found after resolving relative import
        # also sets module
        self.resolved_path = None
        self.needs_resolution = True
        # path for external GIT repo
        self.external_path = None
        # note about relative level of import
        self.level = level


        log = self.logger("__init__")
        log.w(f"({module}, {symbols})")

        self._resolve_path()

    def _resolve_path(self):
        log = self.logger("_resolve_path")
        new_path = None
        if self.relative:
            new_path = PythonPathWrapper(self.statement_file_path)
            # log.w(f"relative path 1: {new_path}")
            new_symbols = new_path.find_relative_import(self.level, self.module, self.symbols)
            # log.d(new_path)
            # log.w(f"relative path 2: {new_path}")
            log.v(f"{self}| {self.path} -> {new_path}")
            self.resolved_path = new_path.str()
            self.module = new_path.module_guess
            self.needs_resolution = False
            self.symbols = new_symbols
            # if not new_symbols:
            #     raise ValueError(f"Could not find relative import! {self}: mod: {self.module}, sym: {self.symbols}")
        else:
            #
            log.v(f"{self}| Path correct")
            # Here we want to resolve the spec before "resolving"
            self._resolve_spec()

    def _find_spec(self, module_name):
        log = self.logger("_find_spec")
        log.v(f"{module_name}")
        if module_name is None:
            log.w(F"{self}: name is none, skipping find spec")
            return module_name, None

        if self.ignore_reason:
            log.v(f'Module "{module_name}" being ignored, not finding spec')
            return module_name, None

        spec = None
        exception = None
        ignore_reason = None

        try:
            spec = find_spec(module_name)
            # clear previous errors on success
        except AttributeError as e:  # __future__ crashes find_spec lol
            ignore_reason = self.ATTRIBUTE_EXCEPTION
            exception = e
        except ModuleNotFoundError as e:  # seen sometimes
            ignore_reason = self.MODULE_NOT_FOUND_EXCEPTION
            exception = e
        except ValueError as e:
            ignore_reason = self.VALUE_EXCEPTION
            exception = e

        if spec is None and '.' in module_name:
            # might be a X from Y situation rendered as X.Y, remove a dot and try that as the module
            (maybe_module, new_member) = module_name.rsplit('.', 1)
            log.w(f'Module "{module_name}" can\'t be found, trying {maybe_module}')

            return self._find_spec(maybe_module)

        if exception:
            self.ignore_reason = ignore_reason
            log.v(f'name "{self}" raised: {exception}')

        return module_name, spec

    def _resolve_spec(self):
        log = self.logger("_find_spec")
        log.v(f"")
        (found_name, spec) = self._find_spec(self.module)

        if spec:
            # dlog(f'Checking if spec is system spec: {spec}')
            if spec.origin and 'site-packages' not in spec.origin:
                # builtin case 1
                log.v(f'Module "{self.module}" is not in sitepackages, it is a builtin.')
                self.ignore_reason = self.SYSTEM_LIBRARY
            elif spec.loader and spec.loader is BuiltinImporter:
                # builtin case 2
                log.v(f'Module "{self.module}" uses the buildin importer.')
                self.ignore_reason = self.SYSTEM_LIBRARY

            # we're importing a submodule we didn't expect
            if found_name != self.module:
                symbols = self.module
                symbols = symbols.replace(found_name, "").strip(".")

                if not self.symbols:
                    # easy case
                    self.symbols = [symbols]
                else:
                    self.symbols = [f'{symbols}.{old_symbol}' for old_symbol in self.symbols]

                log.v(f'{self.module} -> {found_name}; {self.symbols}')
                self.module = found_name

            self.spec = spec
            self.needs_resolution = False
        else:
            # try treating this like a relative import
            if not self.relative:
                try:
                    new_path = PythonPathWrapper(self.statement_file_path)
                    new_symbols = new_path.find_relative_import(1, self.module)
                    log.d(new_path)
                    self.resolved_path = new_path.str()
                    self.ignore_reason = None
                    self.needs_resolution = False
                    self.symbols = new_symbols
                except ValueError:
                    log.w(f'Module "{self.module}" does not appear to be installed in current path.')

    def set_external_path(self, new_path: str):
        log = self.logger("set_external_path")
        self.external_path = PythonPathWrapper(self.path).swap_root(new_path).str()
        log.w(f"self.external_path = {self.external_path}")


    # just in case
    @property
    def name(self):
        return self.module

    @property
    def relative(self):
        return self.level > 0

    @property
    def spec_path(self) -> Optional[str]:
        """
        Get the path associated with the version of this module that exists in the current python environment.
        Will not reflect if we have an external git repo of this path
        :return: str
        """
        sp =  getattr(self.spec, "origin", None)
        # sometimes spec.origin is just a str constant :'(
        if sp == "built-in":
            sp = None # report this as None
        return sp

    # @property
    # def needs_resolution(self):
    #     return self.resolved_path is None

    @property
    def path(self) -> str:
        """
        Get the most correct path for this import. Could have a relative path or could be an external path
        :return: str
        """
        return self.external_path or self.resolved_path or self.spec_path

    @property
    def origin(self):
        """
        Mirror of self.path
        :return:
        """
        return self.path

    @property
    def being_ignored(self):
        return self.ignore_reason is not None

    @property
    def name_str(self):
        if not self.symbols:
            return f'{self._badge}{self.module}'
        else:
            # should always be singular
            level = self.level * "."
            if not self.needs_resolution:
                level = ""
            return f'From {self._badge}{level}{self.module} Import {",".join(self.symbols)}'

    @property
    def _badge(self):
        if self.being_ignored:
            if self.ignore_reason == self.NOT_FOUND:
                return '<!X>'
            if self.ignore_reason == self.SYSTEM_LIBRARY:
                return '<!S>'
            if self.ignore_reason in [self.ATTRIBUTE_EXCEPTION, self.MODULE_NOT_FOUND_EXCEPTION, self.VALUE_EXCEPTION]:
                return '<!E>'

        if self.needs_resolution:
            return '<!U>'

        if self.relative:
            return '<+R>'
        else:
           return '<+A>'

    @property
    def _spec_str(self):
        log = self.logger("_spec_str")
        origin = "None"
        if self.path:
            try:
                origin = PythonPathWrapper(self.path).short_version
            except Exception:
                log.e(f"got exception on path! self.path: {self.path}, self.spec_path: {self.spec_path}, self.resolved_path: {self.resolved_path}, self.extermal: {self.external_path}")

        if self.spec:
            return f'-> S[{self.spec.name}]<{origin}>'
        elif self.needs_resolution:
            return '-> [Needs Resolution]'
        else:
            return '-> [Spec Not Found]'

    def __str__(self):
        if not self.symbols:
            # can appear as multiples
            return f'{self._badge}Import {self.module}{self._spec_str}'
        else:
            mod_str = self.module or ""
            level = self.level * "."
            if not self.needs_resolution:
                level = ""
            return '{}From {}{} Import {}{}'.format(
                self._badge,
                level,
                mod_str,
                ', '.join(self.symbols),
                self._spec_str
            )

    def __repr__(self):
        return str(self)


# todo: Make a 2nd Import helper object that wraps the _act_ of importing a library
# todo: instead of the Import <x> statement in the AST. One Import statement can generate
# todo: many import actions (from X import a, b, c, d). This is why I've been keeping track of
# todo: imports seperately, because each a, b, c, d have different line# and import implications.
class ImportStatement(Logger):
    """ Helper object to track where a particular import statement in a particular file """

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

    def __init__(self, node: ast.AST, file_path: str, src: str, *kwargs):
        super().__init__(*kwargs)
        log = self.logger("__init__")
        # print(f'ImportContex({node}m {parent_wrapper}, {src})')
        if not self.node_is_import(node):
            raise ValueError(f"ImportContext only supports Import and Import from. Not: {node}")

        # self._parent = parent_wrapper
        self._file_path = file_path
        self._node = node
        self._context = src
        self.references: List[ImportReference] = []
        log.d(f"{file_path} -> {node}")

        self._make_reference()

    def _make_reference(self):
        log = self.logger("_make_reference")
        try:
            if self.is_import:
                self.references = [ImportReference(self._file_path, alias.name) for alias in self._node.names]
            else:
                log.d(f"ImportReference({self._file_path}, {self._node.module}, {[alias.name for alias in self._node.names]}, {self._node.level})")
                self.references = [
                    ImportReference(
                        self._file_path,
                        self._node.module,
                        [alias.name for alias in self._node.names],
                        self._node.level
                    )
                ]
        except:
            # print(self._node.lineno)
            raise

    def re_contextualize(self, new_source):
        # print(f'ImportContex.re_contextualize({new_source})')
        c = copy(self)
        c._context = new_source
        return c

    @property
    def is_import(self):
        return self._node.__class__ is ast.Import

    @property
    def local(self):
        return self._context == self.Source_Local

    def __str__(self):
        # return f'[{self._node.lineno}|{self._src}]Import {", ".join(self.names)}'
        if self.is_import:
            return f'[{self._node.lineno}]Import {", ".join([r.name_str for r in self.references])}'
        else:
            return f'[{self._node.lineno}]{self.references[0].name_str}'

    def __repr__(self):
        return str(self)


class PrintCtx(object):
    ctx_obj: str = None
    in_statement: bool = False
    line_number: Optional[int] = None

class IgnoreSymbolException(Exception):
    """
    Thrown when we believe we can safely ignore this symbol and not store it in the table
    """
    def __init__(self, message = None):
        self.message = message


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

    def __init__(self, path: str, node: ast.AST, parent: 'ASTWrapper' = None, log_node = False):
        super().__init__()

        log = self.logger("__init__")
        self.node = node
        self.path = path

        self.parent = parent
        self.log_node = log_node
        self.children = []
        self._first_line = 0
        self._last_line = 0
        self._symbols = {}
        if self._has_line:
            self._first_line = self.line
            self._last_line = self.line

        log.v(f'{self}')
        if self.has_children:
            # log.w(f'>has children')
            child_keys = self._NODES_WITH_CHILDREN_TO_KEYS[self._n_class]
            for key in child_keys:
                container = getattr(self.node, key, None)
                if container:
                    for element in container:
                        self.children.append(self._make_child_wrapper(element))
                    output = '\n\t' + '\n\t'.join([str(c) for c in self.children])
                    # log.w(f'{self.node.__class__.__name__}[{key}] = {output}')

        # self._handle_node_symbol()

        if self.parent is not None:
            # keep track of length of each symbol
            if self._has_line:
                self.parent._child_line_number(self.node.lineno)
            # if self.children: # get list of scope imports
            #     self._imports.extend(self.parent._get_scope_imports())

        if self.log_node or self.is_import:
            log.w(f'({self.path}){self}')

    def _make_child_wrapper(self, element):
        wrapper = ASTWrapper(self.path, element, self, log_node = self.log_node)

        return wrapper

    # def _get_scope_imports(self):
    #     return [i.re_contextualize(ImportStatement.Source_Above) for i in self._imports]

    @property
    def is_import(self):
        return ImportStatement.node_is_import(self.node)

    @property
    def has_children(self):
        return self._n_class in list(self._NODES_WITH_CHILDREN_TO_KEYS.keys())

    @property
    def adds_symbol(self):
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
            level = getattr(node, 'level', None)
            (line_str, ctx) = self._line_number_str(node, ctx)
            if not mod and level:
                # relative import
                return f'{line_str}From {"." * level} import {", ".join(names)}'
            elif mod and level:
                return f'{line_str}From {"." * level}{mod} import {", ".join(names)}'
            else:
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


class ManagedASTWrapper(ASTWrapper):
    _NAME = "MAstWrapper"

    def __init__(self, path: str, node: ast.AST, parent: ASTWrapper = None, log_node=False):
        super().__init__(path, node, parent, log_node)
        self.manager = None

    def set_manager(self, manager):
        log = self.logger("set_manager")
        named = False
        self.manager = manager

        for child in self.children:
            log.v(f"child: {child}")
            if child.is_import:
                stmt = self._make_import_statement(child)
                if not named:
                    log.d(f"{self.path}: {self.node}")
                    named = True
                log.d(f"  import: {child} -> {stmt}")
                self.manager.register_import(stmt)
            if child.adds_symbol:
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


                # todo: This is a sign of messy division of responsibilities - I haven't cleanly
                # todo: set out which layer handles which
                symbol_names, values = child.get_symbol_values()
                last_value = None
                for name in symbol_names:
                    # if counts match, we can just pop them all
                    if len(values):
                        last_value = self._make_child_wrapper(values.pop(0))

                    # todo: create some kind of index reference!
                    self.manager.register_symbol(name, last_value)



    def _make_child_wrapper(self, element):
        log = self.logger("_make_child_wrapper")
        wrapper = ManagedASTWrapper(self.path, element, self, log_node = self.log_node)

        return wrapper

    def _make_import_statement(self, node):
        log = self.logger("_make_import_statement")
        log.w(f"{node}")
        node = node
        if isinstance(node, ASTWrapper):
            node = node.node

        log.w(f"ImportStatement({node}, {self.path}, local)")
        return ImportStatement(node, self.path, ImportStatement.Source_Local)

    def get_symbol_values(self):
        log = self.logger("_handle_node_symbol")
        log.v("")
        # if not self.adds_symbol or not self.parent:
        if self.adds_symbol:
            # find and add symbols to table
            member_name = self._NODES_THAT_ADD_TO_SYMBOL_TABLE_TO_KEY[self._n_class]
            symbol_member = getattr(self.node, member_name, None)

            if symbol_member is None:
                raise ValueError(f"{self}: expected to find a symbol!")

            values = [self._get_r_side_node()]
            # self.wlog('_i_:node_adds_symbol', f'{self}({symbol_member})')
            if self._n_class in self._SYMBOL_BY_EXPR:
                # Symbol is contained in an expression, that must be resolved first
                try:
                    symbol_names = self._resolve_expr_symbols(symbol_member)
                except IgnoreSymbolException as e:
                    log.w(f'{e.message}')
                    symbol_names = []
            else:
                # symbol is contained in an id, which is just a string, so we already have it in symbol_member
                symbol_names = [symbol_member]  # makes the processing easier if it's always a list

            if len(symbol_names) > 0:
                if len(symbol_names) > 1 and len(values) == 1:
                    # try unpacking the values
                    values = self._try_explode_values(values[0])

                    if len(symbol_names) > 1 and len(values) == 1:
                        log.d(f"many symbols to one value! Likely a function unpacking!\n\t\t\t\t{self}")
                elif len(symbol_names) != len(values):
                    log.w(
                        f"{len(symbol_names)}syms != {len(values)}vals! Symbol table may be flawed!\n\t\t\t\t{self}")

                return symbol_names, values
            # else:
            #     log.w('_handle_node_symbol', f'Skipping add because we generated no symbols')

        return [], []


    def _get_r_side_node(self):
        log = self.logger("_get_r_side_node")
        log.v(f"{self.node}")

        # FunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
        # | AsyncFunctionDef(identifier name, arguments args, stmt* body, expr* decorator_list, expr? returns)
        # | ClassDef(identifier name, expr* bases, keyword* keywords, stmt* body, expr* decorator_list)
        # | Assign(expr* targets, expr value)
        # | AugAssign(expr target, operator op, expr value)
        # | AnnAssign(expr target, expr annotation, expr? value, int simple)

        node = self.node
        # get the right hand side of the statement
        if isinstance(node, ast.Assign):
            node = node.value
        elif isinstance(node, ast.AugAssign):
            node = node.value
        elif isinstance(node, ast.AnnAssign):
            node = node.value

        return node

    def _try_explode_values(self, node):
        log = self.logger("_try_explode_values")
        values = []

        if isinstance(node, ast.Tuple):
            # | Tuple(expr* elts, expr_context ctx)
            for expr in node.elts:
                values.append(expr)
        else:
            values.append(node)

        return values

    def _resolve_expr_symbols(self, exprs):
        log = self.logger("_handle_node_symbol")
        if not isinstance(exprs, list):
            exprs = [exprs]

        # log.v(f'Exprs: {", ".join([self.node_str(e) for e in exprs])}')
        # log.v(f'Exprs: {exprs}')
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
                # [2493]{table_user}{passfield}.{requires}[-= #1].{min_length} = #0
                # ->
                # table_user[passfield].requires[-1].min_length
                # expected to have value of
                if not isinstance(value_strings, list) or len(value_strings) != 1:
                    log.e(f"value: {self.node_str(e.value)}, id: {e.attr}")
                    raise Exception(f"{self}:This is an unexpected format: {value_strings}")
                out.append(f'{value_strings[0]}.{e.attr}')
            elif isinstance(e, ast.Tuple):
                # | Tuple(expr* elts, expr_context ctx)
                for expr in e.elts:
                    for identifier in self._resolve_expr_symbols(expr):
                        out.append(identifier)
            elif isinstance(e, ast.Subscript):
                # | Subscript(expr value, slice slice, expr_context ctx)
                # This will always be adding a symbol to something that's already in our symbol table and I think we can safely ignore it
                raise IgnoreSymbolException(f'Found {self.node_str(e)} when resolving symbols in {self} - abandoning symbol resolution.')
            else:
                log.w(f'\tExpr({e})({self.node_str(e)}) does not seem to generate a symbol, skipping')
                continue

            # log.d('_resolve_expr_symbols', f'\t{out}')
            result.extend(out)

        return result

class StatNode(Logger):
    """
    Helper class to track the statistics branching from a particular node
    """

    _NAME = "StatNode"

    def __init__(self, path: str, first_line: int, last_line: int,
                 symbol: str = None, links: List[ImportReference] = None, **kwargs):
        super().__init__(**kwargs)
        self.path_to_file = path
        self.first_line = first_line
        self.last_line = last_line
        self.symbol = symbol
        self.links: List[ImportReference] = []
        if links:
            self.links = links

    @property
    def length(self):
        return self.last_line - self.first_line


    def __str__(self):
        p = PythonPathWrapper(self.path_to_file)
        name = p.short_version
        if self.symbol:
            name = self.symbol
        return f'St[{name}][{self.length}] -> [{len(self.links)}]'

class SymbolManager(Logger):
    """
    Tracks the imports in a symbol and store the AST tree

    Knows nothing about actual files and just passes around references
    """

    _NAME = "Symbol"

    def __init__(self, name: str, ast: ManagedASTWrapper, **kwargs):
        super().__init__(**kwargs)

        self.name = name
        self.ast: ManagedASTWrapper = ast
        self.scope_imports : List[ImportStatement] = []
        self.symbols: Dict[str, SymbolManager] = {}
        self._symbol_refs: Dict[str, SymbolManager] = {}

    def register_symbol(self, name: str, value: ManagedASTWrapper) -> None:
        # make child symbol
        self.symbols[name] = SymbolManager(name, value)
        # tell the value it has a manager now
        value.set_manager(self.symbols[name])

    def register_import(self, statement: ImportStatement) -> None:
        # log = self.logger("register_import")
        # log.d(f"{self.name}: {self.scope_imports} += {statement}")
        self.scope_imports.append(statement)

    def stats(self, symbol = None):
        return StatNode(
            self.ast.path,
            self.ast.first_line,
            self.ast.last_line,
            self.name,
            self.imports(symbol)
        )

    def imports(self, symbol = None) -> List[ImportReference]:
        log = self.logger("imports")
        # log.d(f"{self.name} imports()")
        imps = []
        for i in self.scope_imports:
            # log.d(f"Adding global imports: {i.references}")
            imps.extend(i.references)
        if symbol is not None and symbol in self.symbols:
            # log.d(f"Adding imports for one symbol '{symbol}': {self.symbols[symbol].imports()}")
            imps.extend(self.symbols[symbol].imports())
        else:
            for k, c in self.symbols.items():
                # log.d(f"Adding imports for symbol '{k}'")
                imps.extend(c.imports())

        return imps

    @property
    def has_imports(self) -> bool:
        return len(self.imports()) > 0

    @property
    def symbols_with_imports(self) -> Dict[str, 'SymbolManager']:
        return {k:v for k, v in self.symbols.items() if v.has_imports}

    def imp_str(self):
        imports_str = ""
        symbols_str = ""
        if self.scope_imports:
            imports_str = 'Imports:\n{}'.format(
                self.indent([str(i) for i in self.scope_imports])
            )
        if self.symbols_with_imports:
            symbols_str = 'Symbols:\n{}'.format(
                self.indent([v.imp_str() for k, v in self.symbols_with_imports.items()])
            )
            if self.scope_imports:
                symbols_str = "\n" + symbols_str

        return 'SM[{}]-> {}\n{}{}'.format(
            self.name, self.ast,
            self.indent(imports_str),
            self.indent(symbols_str)
        )

    def sum_str(self):
        imports_str = ""
        symbols_str = ""
        if self.scope_imports:
            imports_str = 'Imports:\n{}'.format(
                self.indent([str(i) for i in self.scope_imports])
            )

        if self.symbols:
            symbols_str = 'Symbols:\n{}'.format(
                self.indent([v.sum_str() for k, v in self.symbols.items()])
            )
            if self.scope_imports:
                symbols_str = "\n" + symbols_str

        return 'SM[{}]-> {}\n{}{}'.format(
            self.name, self.ast,
            self.indent(imports_str),
            self.indent(symbols_str)
        )

    def __str__(self):
        return self.imp_str()

    def __repr__(self):
        return str(self)


class ModuleManager(Logger):
    """
    May just be a re-treading of ModuleListingWrapper
    """

    _NAME = "ModuleManager"

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)

        self.path = PythonPathWrapper(path)

        if not self.path.is_py_file:
            raise ValueError(f"Path '{self.path}' does not appear to by a python file!")

        wrapper = ManagedASTWrapper(
            self.path.str(),
            ast.parse(self.path.read(), filename=self.path.str())
        )

        self.symbols = SymbolManager(self.module, wrapper)
        wrapper.set_manager(self.symbols)

    def get_stat(self, symbol = None):
        return self.symbols.stats(symbol)

    @property
    def imports(self) -> List[ImportReference]:
        return self.symbols.imports()

    @property
    def valid_import_paths(self) -> List[str]:
        paths = []
        for i in self.imports:
            if not i.being_ignored and i.path:
                paths.append(i.path)

        return paths

    @property
    def module(self):
        return self.path.module_guess