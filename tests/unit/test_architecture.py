import ast
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "cintel"

_LAYER_RULES = {
    "domain": {"domain"},
    "ports": {"domain", "ports"},
    "utilities": {"utilities"},
    "configuration": {"configuration", "domain"},
    "adapters": {"adapters", "domain", "ports", "utilities"},
    "application": {
        "application",
        "configuration",
        "domain",
        "ports",
        "utilities",
    },
}


def _modules():
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            yield path, ".".join(parts)


def _cintel_imports(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "cintel" or node.module.startswith("cintel."):
                yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "cintel" or alias.name.startswith("cintel."):
                    yield alias.name


def _stdlib_imports(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


class ArchitectureTests(unittest.TestCase):
    def test_layers_only_import_inward(self) -> None:
        violations = []
        for path, module in _modules():
            layer = module.split(".")[0]
            allowed = _LAYER_RULES.get(layer)
            if allowed is None or "." not in module:
                continue
            for imported in _cintel_imports(ast.parse(path.read_text(encoding="utf-8"))):
                parts = imported.split(".")
                if len(parts) < 2 or parts[0] != "cintel":
                    continue
                if parts[1] not in allowed:
                    violations.append(f"{module} imports {imported}")
        self.assertEqual([], violations)

    def test_subprocess_is_confined_to_the_command_runner(self) -> None:
        found = [
            module
            for path, module in _modules()
            if "subprocess" in set(_stdlib_imports(ast.parse(path.read_text(encoding="utf-8"))))
        ]
        self.assertEqual(["adapters.commands.subprocess_runner"], found)

    def test_sqlite_is_confined_to_the_storage_adapter(self) -> None:
        found = [
            module
            for path, module in _modules()
            if "sqlite3" in set(_stdlib_imports(ast.parse(path.read_text(encoding="utf-8"))))
        ]
        self.assertTrue(found)
        for module in found:
            self.assertTrue(
                module.startswith("adapters.storage."),
                f"{module} imports sqlite3 outside the storage adapter",
            )


if __name__ == "__main__":
    unittest.main()
