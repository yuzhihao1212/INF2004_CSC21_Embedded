"""CSC21 source enforcement: the clock adapter is the only float boundary."""
import ast
import unittest
from pathlib import Path

ALLOW_LIST = {'reference.py': {'seconds_to_ms'}, 'fusion.py': set()}


def violations(source, allowed):
    errors = []
    class Audit(ast.NodeVisitor):
        scope = []
        def visit_ClassDef(self, node):
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()
        def visit_FunctionDef(self, node):
            if self.scope or node.name not in allowed:
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()
        def bad(self, node, reason):
            errors.append((node.lineno, reason))
        def visit_Constant(self, node):
            if isinstance(node.value, (float, complex)):
                self.bad(node, 'floating literal')
        def visit_BinOp(self, node):
            if isinstance(node.op, ast.Div):
                self.bad(node, 'true division')
            if isinstance(node.op, ast.Pow) and not (isinstance(node.right, ast.Constant)
                                                    and type(node.right.value) is int
                                                    and node.right.value >= 0):
                self.bad(node, 'noninteger/negative exponent')
            self.generic_visit(node)
        def visit_Name(self, node):
            if node.id in {'float', 'complex', 'pow', 'eval', 'exec', 'getattr', '__import__'}:
                self.bad(node, 'floating/dynamic operation: ' + node.id)
        def visit_AugAssign(self, node):
            if isinstance(node.op, ast.Div):
                self.bad(node, 'true division assignment')
            self.generic_visit(node)
        def visit_Attribute(self, node):
            if node.attr in {'temperature_c', 'humidity_pct', 'rms'}:
                self.bad(node, 'decimal telemetry accessor: ' + node.attr)
            if isinstance(node.value, ast.Name) and node.value.id == 'math':
                if node.attr not in {'gcd'}:
                    self.bad(node, 'noninteger math operation: ' + node.attr)
            self.generic_visit(node)
        def visit_Import(self, node):
            if any(a.name not in {'enum', 'json', 'math'} or a.asname for a in node.names):
                self.bad(node, 'unreviewed numeric import/alias')
        def visit_ImportFrom(self, node):
            if node.module not in {'__future__', 'collections', 'dataclasses', 'pathlib',
                                   'typing', 'mosaic', 'mosaic.reference'}:
                self.bad(node, 'unreviewed numeric import')
    Audit().visit(ast.parse(source))
    return errors


class IntegerEnforcement(unittest.TestCase):
    def test_processing_sources_have_no_floating_operations(self):
        print('INTEGER BOUNDARY ALLOW-LIST:', {k: sorted(v) for k, v in ALLOW_LIST.items()})
        base = Path(__file__).parents[1] / 'mosaic'
        for name, allowed in ALLOW_LIST.items():
            with self.subTest(module=name):
                self.assertEqual(violations((base / name).read_text(), allowed), [])

    def test_audit_rejects_float_shortcuts(self):
        for expression in ('1.5', '1 / 2', 'float(1)', 'math.sqrt(4)', 'math.exp(1)',
                           'math.log(2)', '2 ** -1', 'pow(2, -1)', 't.temperature_c', 't.rms'):
            with self.subTest(expression=expression):
                self.assertTrue(violations('def process(): return ' + expression, set()))
        for source in ('import math as m\nx = m.sqrt(4)', 'from math import sqrt', 'x /= 2',
                       'class Hidden:\n def seconds_to_ms(self): return 1.5'):
            self.assertTrue(violations(source, {'seconds_to_ms'}))
        self.assertEqual(violations('def seconds_to_ms(now): return int(now * 1000 + 0.5)',
                                    {'seconds_to_ms'}), [])
