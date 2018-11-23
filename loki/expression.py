from abc import ABCMeta, abstractproperty
from sympy.core.cache import cacheit, SYMPY_CACHE_SIZE
import sympy
from sympy.core.numbers import One as SympyOne
from collections import Iterable

from loki.visitors import GenericVisitor, Visitor
from loki.tools import flatten, as_tuple
from loki.logging import warning

__all__ = ['Expression', 'Operation', 'Literal', 'Scalar', 'Array',
           'Variable', 'Cast', 'Index', 'RangeIndex',
           'ExpressionVisitor', 'LiteralList', 'FindVariables',
           '_symbol_type', 'indexify']


def _symbol_type(cls, name, parent=None):
    """
    Create new type instance from cls and inject symbol name
    """
    # Add the parent-object if it exists (`parent`)
    parent = ('%s%%' % parent) if parent is not None else ''
    name = '%s%s' % (parent, name)
    return type(name, (cls, ), dict(cls.__dict__))


def indexify(expr):
    mapper = {}
    for e in sympy.postorder_traversal(expr):
        try:
            mapper[e] = e.indexify()
        except:
            pass
    return expr.xreplace(mapper)


"""
A global cache of modified symbol class objects
"""
_global_symbol_type = cacheit(_symbol_type)


class ExpressionVisitor(GenericVisitor):

    def visit_Statement(self, o, **kwargs):
        return tuple([self.visit(o.target, **kwargs), self.visit(o.expr, **kwargs)])

    def visit_Expression(self, o, **kwargs):
        return tuple(self.visit(c, **kwargs) for c in o.children)


class FindVariables(ExpressionVisitor, Visitor):
    """
    A dedicated visitor to collect all variables used in an IR tree.

    Note: With `unique=False` all variables instanecs are traversed,
    allowing us to change them in-place. Conversely, `unique=True`
    returns a :class:`set` of unique :class:`Variable` objects that
    can be used to check if a particular variable is used in a given
    context.

    Note: :class:`Variable` objects are not recursed on in themselves.
    That means that individual component variables or dimension indices
    are not traversed or included in the final :class:`set`.
    """

    def __init__(self, unique=True):
        super(FindVariables, self).__init__()
        self.unique = unique

    default_retval = tuple

    def visit_tuple(self, o):
        vars = flatten(self.visit(c) for c in o)
        return set(vars) if self.unique else vars

    visit_list = visit_tuple

    def visit_Variable(self, o):
        dims = flatten(self.visit(d) for d in o.dimensions)
        return set(dims + [o]) if self.unique else tuple(dims + [o])

    def visit_Expression(self, o):
        vars = flatten(self.visit(c) for c in o.children)
        return set(vars) if self.unique else vars

    visit_InlineCall = visit_Expression

    def visit_Statement(self, o, **kwargs):
        vars = as_tuple(self.visit(o.expr, **kwargs))
        vars += as_tuple(self.visit(o.target))
        return set(vars) if self.unique else as_tuple(vars)

    def visit_Loop(self, o, **kwargs):
        vars = flatten(self.visit(o.variable) for c in o.children)
        vars += flatten(self.visit(o.bounds.lower) for c in o.children)
        vars += flatten(self.visit(o.bounds.upper) for c in o.children)
        vars += flatten(self.visit(o.bounds.step) for c in o.children)
        vars += flatten(self.visit(o.body) for c in o.children)
        return set(vars) if self.unique else as_tuple(vars)


class Expression(object):
    """
    Base class for aithmetic and logical expressions.

    Note: :class:`Expression` objects are not part of the IR hierarchy,
    because re-building each individual expression tree during
    :class:`Transformer` passes can quickly become much more costly
    than re-building the control flow structures.
    """

    __metaclass__ = ABCMeta

    def __init__(self, source=None):
        self._source = source

    @abstractproperty
    def expr(self):
        """
        Symbolic representation - might be used in this raw form
        for code generation.
        """
        pass

    @abstractproperty
    def type(self):
        """
        Data type of (sub-)expressions.

        Note, that this is the pure data type (eg. int32, float64),
        not the full variable declaration type (allocatable, pointer,
        etc.). This is so that we may reason about it recursively.
        """
        pass

    def __repr__(self):
        return self.expr

    @property
    def children(self):
        return ()


class Scalar(sympy.Symbol):

    is_Scalar = True
    is_Array = False

    def __new__(cls, *args, **kwargs):
        """
        1st-level variable creation with name injection via the object class
        """
        name = kwargs.pop('name')
        parent = kwargs.pop('parent', None)

        # Name injection for sympy.Symbol (so we can do `a%scalar`)
        if parent is not None:
            name = '%s%%%s' % (parent, name)

        # Create a new object from the static constructor with global caching!
        return Scalar.__xnew_cached_(cls, name, parent=parent)

    def __new_stage2__(cls, name, parent=None):
        """
        2nd-level constructor: arguments to this constructor are used
        for symbolic caching
        """
        # Create a new class object to inject custom variable naming
        # newcls = _symbol_type(cls, name, parent)

        # Setting things here before __init__ forces them
        # to be used for symbolic caching. Thus, `parent` is
        # always used for caching, even if it's not in the name
        newobj = sympy.Symbol.__new__(cls, name)
        newobj.name = name
        newobj.parent = parent

        return newobj

    # Create a globally cached symbol constructor.
    __xnew_cached_ = staticmethod(cacheit(__new_stage2__))

    def __init__(self, *args, **kwargs):
        """
        Initialisation of non-cached objects attributes
        """
        self._source = kwargs.pop('source', None)
        self.initial = kwargs.pop('initial', None)


class Array(sympy.Function):

    is_Scalar = False
    is_Array = True

    def __new__(cls, *args, **kwargs):
        """
        1st-level variable creation with name injection via the object class
        """
        if cls == Array:
            # An original constructor invocation
            name = kwargs.pop('name')
            dimensions = kwargs.pop('dimensions', None)
            parent = kwargs.pop('parent', None)

            # Inject the symbol name into the class object.
            # Note, this is the SymPy way to inject custom
            # function naming and ensure symbol caching.
            cls = _global_symbol_type(cls, name, parent)
        else:
            # A reconstruction of an array(function) object,
            # as triggered during symbolic manipulation.
            name = cls.__name__
            dimensions = args
            parent = kwargs.pop('parent', None)

        # Create a new object from the static constructor with global caching!
        return Array.__xnew_cached_(cls, name, dimensions, parent=parent)

    def __new_stage2__(cls, name, dimensions, parent=None):
        """
        2nd-level constructor: arguments to this constructor are used
        for symbolic caching
        """
        # Setting things here before __init__ forces them
        # to be used for symbolic caching. Thus, `parent` is
        # always used for caching, even if it's not in the name
        newobj = sympy.Function.__new__(cls, *dimensions)
        newobj.name = name
        newobj.dimensions = dimensions
        newobj.parent = parent

        return newobj

    # Use the sympy.core.cache.cacheit decorator to a kernel to create
    # a static globally cached symbol constructor.
    __xnew_cached_ = staticmethod(cacheit(__new_stage2__))

    def __init__(self, *args, **kwargs):
        """
        Initialisation of non-cached objects attributes
        """
        self._source = kwargs.pop('source', None)
        self.initial = kwargs.pop('initial', None)

    def _fcode(self, printer=None):
        """
        Define how we would like to be printed in Fortran code.
        """
        return str(self)

    @property
    def indexed(self):
        name = self.name if self.parent is None else '%s%%%s' % (self.parent, self.name)
        return sympy.IndexedBase(name, shape=self.args)

    def indexify(self):
        return self.indexed[self.args]


class Variable(sympy.Function):
    """
    A symbolic object representing either a :class:`Scalar` or a :class:`Array`
    variable in arithmetic expressions.
    """

    def __new__(cls, *args, **kwargs):
        """
        1st-level variables creation with name injection via the object class
        """
        name = kwargs.pop('name')
        dimensions = kwargs.pop('dimensions', None)
        parent = kwargs.pop('parent', None)

        # Create a new object from the static constructor with global caching!
        if dimensions is None:
            v = Scalar.__new__(Scalar, name=name, parent=parent)
        else:
            v = Array.__new__(Array, name=name, dimensions=dimensions, parent=parent)

        v.__init__(*args, **kwargs)
        return v

    # def __init__(self, *args, **kwargs):
    #     """
    #     Initialisation of non-cached objects attributes

    #     Important: Despite the caching in __new__, __init__ will
    #     always be executed when creating a new :class:`Variable` via the
    #     global constructor, due to the direct inheritance from
    #     sympy.Function.__new__. This means providing a value can
    #     overwrite previous values on a previous instance due to caching.
    #     """
    #     self.meta = kwargs.pop('meta', None)
    #     self._type = kwargs.pop('type', None)
    #     self._shape = kwargs.pop('shape', None)
    #     self.initial = kwargs.pop('initial', None)


    # def __init__(self, name, type=None, shape=None, dimensions=None,
    #              ref=None, initial=None, source=None):
    #     super(Variable, self).__init__(source=source)
    #     self._source = source

    #     self.name = name
    #     self._type = type
    #     self._shape = shape
    #     self.ref = ref  # Derived-type parent object
    #     self.dimensions = dimensions or ()
    #     self.initial = initial

    # @property
    # def expr(self):
    #     idx = ''
    #     if self.dimensions is not None and len(self.dimensions) > 0:
    #         idx = '(%s)' % ','.join([str(i) for i in self.dimensions])
    #     parent = '' if self.parent is None else '%s%%' % str(self.parent)
    #     return '%s%s%s' % (parent, self.name, idx)

    @property
    def type(self):
        return self._type

    @property
    def shape(self):
        """
        Original allocated shape of the variable as a tuple of dimensions.
        """
        return self._shape

    # def __key(self):
    #     return (self.name, self.type, self.dimensions, self.parent)

    # def __hash__(self):
    #     return hash(self.__key())

    # def __eq__(self, other):
    #     # Allow direct comparison to string and other Variable objects
    #     if isinstance(other, str):
    #         return str(self).upper() == other.upper()
    #     elif isinstance(other, Variable):
    #         return self.__key() == other.__key()
    #     else:
    #         return super(Variable, self).__eq__(other)

    @property
    def children(self):
        c = self.dimensions
        if self.parent is not None:
            c += (self.parent, )
        return c


class Operation(Expression):

    def __init__(self, ops, operands, parenthesis=False, source=None):
        super(Operation, self).__init__(source=source)
        self.ops = as_tuple(ops)
        self.operands = as_tuple(operands)
        self.parenthesis = parenthesis

    @property
    def expr(self):
        if len(self.ops) == 1 and len(self.operands) == 1:
            # Special case: a unary operator
            return '%s%s' % (self.ops[0], self.operands[0])

        s = str(self.operands[0])
        s += ''.join(['%s%s' % (o, str(e)) for o, e in zip(self.ops, self.operands[1:])])
        return ('(%s)' % s) if self.parenthesis else s

    @property
    def type(self):
        types = [o.type for o in self.operands]
        assert(all(types == types[0]))
        return types[0]

    @property
    def children(self):
        return self.operands

    def __key(self):
        return (self.ops, self.operands, self.parenthesis)

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        # Allow direct comparisong to string and other Index objects
        if isinstance(other, str):
            return self.expr.upper() == other.upper()
        elif isinstance(other, Operation):
            return self.__key() == other.__key()
        else:
            return super(Operation, self).__eq__(other)


class FloatLiteral(sympy.Float):
    __slots__ = ['_mpf_', '_prec','_type', '_kind']


class IntLiteral(sympy.Integer):
    __slots__ = ['p', '_type', '_kind']


class Literal(sympy.Number):

    def __new__(cls, value, **kwargs):
        # We first create a dummy object to determine
        # SymPy's internal literal type, so that we can
        # the create the corrected slotted type for it.
        dummy = sympy.sympify(value)
        if dummy.is_Integer:
            obj = sympy.Expr.__new__(IntLiteral)
        elif dummy.is_Float:
            obj = sympy.Expr.__new__(FloatLiteral)
        else:
            # We only overload integer and floats
            return dummy

        # Then we copy over the defining slotted attributes
        if isinstance(dummy, SympyOne):
            # One is treated specially in SymPy (as a singletone)
            obj.p = SympyOne.p
        else:
            for attr in dummy.__class__.__slots__:
                setattr(obj, attr, getattr(dummy, attr))

        # And attach out own meta-data
        obj._type = kwargs.get('type', None)
        obj._kind = kwargs.get('kind', None)
        return obj


class LiteralList(Expression):

    def __new__(self, values):
        return tuple(Literal(v) for v in values)


class InlineCall(sympy.codegen.ast.FunctionCall):
    """
    Internal representation of an in-line function call
    """
    __slots__ = ['name', 'arguments', 'kwarguments']

    defaults = {'arguments': tuple(), 'kwarguments': dict()}

    def __init__(self, name, arguments=None, kwarguments=None):
        self.name = name
        self.arguments = arguments
        self.kwarguments = kwarguments

    @property
    def function_args(self):
        """
        Construct function arguments (required by sympy code printers)
        """
        kwargs = ()
        if self.kwarguments:
            kwargs = tuple(sympy.codegen.ast.Assignment(kw, arg)
                           for kw,arg in self.kwarguments.items())
        return as_tuple(self.arguments) + kwargs

    @property
    def expr(self):
        kwargs = tuple('%s=%s' % (k, v) for k, v in as_tuple(self.kwarguments))
        args = as_tuple(self.arguments) + kwargs
        return '%s(%s)' % (self.name, ','.join(str(a) for a in args))

    @property
    def children(self):
        return self.arguments


class Cast(Expression):
    """
    Internal representation of a data cast to a psecific type.
    """

    def __init__(self, expr, type):
        self._expr = expr
        self._type = type

    @property
    def expr(self):
        return '%s' % self._expr

    @property
    def type(self):
        return self._type

    @property
    def children(self):
        return as_tuple(self._expr)


class Index(Expression):

    def __init__(self, name):
        self.name = name

    @property
    def expr(self):
        return '%s' % self.name

    def __key(self):
        return (self.name)

    def __hash__(self):
        return hash(self.__key())

    @property
    def type(self):
        # TODO: Some common form of `INT`, maybe?
        return None

    def __eq__(self, other):
        # Allow direct comparisong to string and other Index objects
        if isinstance(other, str):
            return self.name.upper() == other.upper()
        elif isinstance(other, Index):
            return self.name == other.name
        else:
            return super(Index, self).__eq__(other)


class RangeIndex(Expression):

    def __new__(cls, lower=None, upper=None, step=None):
        index = '%s:%s' % (lower or '', upper or '')
        index = index if step is None else '%s:%s' (index, step)
        return sympy.Idx(index)
