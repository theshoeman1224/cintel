"""Ratchet tests: modules, classes, and public functions stay documented.

Scope follows the Phase 4 plan. Every module needs a docstring. Classes in
ports, application, cli, adapters, configuration, and the composition root
need one. Public functions and methods in ports, application, cli,
configuration, and the storage adapter need one. Private names and overload
stubs are exempt.
"""

import ast
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "cintel"

CLASS_PACKAGES = {"ports", "application", "cli", "adapters", "configuration"}
FUNCTION_PACKAGES = {"ports", "application", "cli", "configuration"}


def _modules():
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            yield path, ".".join(parts)


def _defined(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            yield node
            if node.name.startswith("_"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield item
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _is_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = node.body
    return (
        len(body) == 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and body[0].value.value is Ellipsis
    )


class DocumentationTests(unittest.TestCase):
    def test_every_module_has_a_docstring(self) -> None:
        missing = [
            module
            for path, module in _modules()
            if not ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        ]
        self.assertEqual([], missing)

    def test_target_classes_are_documented(self) -> None:
        missing = []
        for path, module in _modules():
            if module.split(".")[0] not in CLASS_PACKAGES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if (
                    isinstance(node, ast.ClassDef)
                    and not node.name.startswith("_")
                    and not ast.get_docstring(node)
                ):
                    missing.append(f"{module}:{node.lineno} {node.name}")
        self.assertEqual([], missing)

    def test_target_public_functions_are_documented(self) -> None:
        missing = []
        for path, module in _modules():
            root = module.split(".")[0]
            if root not in FUNCTION_PACKAGES and not module.startswith(
                "adapters.storage"
            ):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in _defined(tree):
                if node.name.startswith("_") or _is_stub(node):
                    continue
                if not ast.get_docstring(node):
                    missing.append(f"{module}:{node.lineno} {node.name}")
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
