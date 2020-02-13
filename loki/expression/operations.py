"""
Sub-classes of Pymbolic's native operations that allow us to express
niche things like mathematically irrelevant parenthesis that
nevertheless change code results.
"""

import pymbolic.primitives as pmbl
from six.moves import intern

from loki.expression.visitors import LokiStringifyMapper
from loki.expression.symbol_types import StringLiteral


class ParenthesisedAdd(pmbl.Sum):
    """
    Specialised version of :class:`Sum` that always pretty-prints and
    code-generates with explicit parentheses.
    """

    mapper_method = intern("map_parenthesised_add")

    def make_stringifier(self, originating_stringifier=None):
        return LokiStringifyMapper()


class ParenthesisedMul(pmbl.Product):
    """
    Specialised version of :class:`Product` that always pretty-prints and
    code-generates with explicit parentheses.
    """

    mapper_method = intern("map_parenthesised_mul")

    def make_stringifier(self, originating_stringifier=None):
        return LokiStringifyMapper()


class ParenthesisedPow(pmbl.Power):
    """
    Specialised version of :class:`Power` that always pretty-prints and
    code-generates with explicit parentheses.
    """

    mapper_method = intern("map_parenthesised_pow")

    def make_stringifier(self, originating_stringifier=None):
        return LokiStringifyMapper()


class StringConcat(pmbl._MultiChildExpression):
    """
    Implements string concatenation in a way similar to :class:`Sum`.
    """

    def __add__(self, other):
        if isinstance(other, (StringConcat, StringLiteral, pmbl.Variable)):
            return StringConcat((self, other))
        if not other:
            return self
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, (StringConcat, StringLiteral, pmbl.Variable)):
            return StringConcat((other, self))
        if not other:
            return self
        return NotImplemented

    def __bool__(self):
        if len(self.children) == 1:
            return bool(self.children[0])
        return True

    __nonzero__ = __bool__

    mapper_method = intern("map_string_concat")
