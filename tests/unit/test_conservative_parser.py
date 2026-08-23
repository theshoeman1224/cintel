import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.parsing import ConservativeCSourceParser, mask_c_non_code
from cintel.domain.models import (
    CallRelationship,
    FileKind,
    FunctionSymbol,
    GlobalUsageRelationship,
    IncludeRelationship,
    Linkage,
    MacroSymbol,
    RelationshipResolution,
    RepositoryFile,
    SourceAnalysisStatus,
    TypeSymbol,
    VariableSymbol,
)


class ConservativeCSourceParserTests(unittest.TestCase):
    def test_masks_comments_strings_and_character_literals_without_moving_offsets(self) -> None:
        source = (
            'int visible;\n'
            '// int hidden_comment;\n'
            'const char *text = "int hidden_string(void) { }";\n'
            "int character = '}'; /* extern int hidden_block; */\n"
        )

        result = mask_c_non_code(source)

        self.assertEqual(len(source), len(result.text))
        self.assertEqual(source.count("\n"), result.text.count("\n"))
        self.assertIn("int visible", result.text)
        self.assertNotIn("hidden_comment", result.text)
        self.assertNotIn("hidden_string", result.text)
        self.assertNotIn("hidden_block", result.text)
        self.assertEqual((), result.issues)

    def test_extracts_includes_and_object_and_function_macros(self) -> None:
        source = (
            '#include "project/api.h"\n'
            "#include <stdint.h>\n"
            "#define LIMIT 16\n"
            "#define SCALE(value, factor) ((value) * (factor))\n"
        )
        with self._parse(source, suffix=".h") as result:
            includes = [
                item
                for item in result.relationships
                if isinstance(item, IncludeRelationship)
            ]
            macros = {
                item.name: item
                for item in result.symbols
                if isinstance(item, MacroSymbol)
            }

            self.assertEqual(
                ["project/api.h", "stdint.h"],
                [item.included_spelling for item in includes],
            )
            self.assertFalse(macros["LIMIT"].is_function_like)
            self.assertEqual("16", macros["LIMIT"].replacement)
            self.assertTrue(macros["SCALE"].is_function_like)
            self.assertEqual(("value", "factor"), macros["SCALE"].parameters)
            self.assertEqual(3, macros["LIMIT"].location.line)
            self.assertEqual((), result.diagnostics)

    def test_extracts_function_declarations_definitions_and_static_linkage(self) -> None:
        source = (
            "extern int declared(const char *name, unsigned count);\n"
            "static int helper(int value)\n"
            "{\n"
            '    const char *decoy = "fake(void) { return 1; }";\n'
            "    return value + 1;\n"
            "}\n"
            "void public_api(void) { }\n"
        )
        with self._parse(source) as result:
            functions = [
                item for item in result.symbols if isinstance(item, FunctionSymbol)
            ]
            by_name = {item.name: item for item in functions}

            self.assertEqual({"declared", "helper", "public_api"}, set(by_name))
            self.assertFalse(by_name["declared"].is_definition)
            self.assertEqual(("const char *name", "unsigned count"), by_name["declared"].parameters)
            self.assertTrue(by_name["helper"].is_definition)
            self.assertEqual(Linkage.INTERNAL, by_name["helper"].linkage)
            self.assertEqual("int", by_name["helper"].return_type)
            self.assertEqual(2, by_name["helper"].location.line)
            self.assertGreaterEqual(by_name["helper"].location.end_line or 0, 6)
            self.assertGreater(by_name["helper"].confidence, 0)
            self.assertTrue(by_name["helper"].evidence)
            self.assertIsNotNone(by_name["helper"].evidence[0].location)
            self.assertEqual((), by_name["public_api"].parameters)
            self.assertNotIn("fake", by_name)

    def test_static_symbol_identity_is_stable_and_file_scoped(self) -> None:
        source = "static int duplicate(void) { return 1; }\n"
        with self._parse(source, file_id="file-a") as first:
            with self._parse(source, file_id="file-a") as repeated:
                with self._parse(source, file_id="file-b") as second_file:
                    first_symbol = next(
                        item
                        for item in first.symbols
                        if isinstance(item, FunctionSymbol)
                    )
                    repeated_symbol = next(
                        item
                        for item in repeated.symbols
                        if isinstance(item, FunctionSymbol)
                    )
                    second_symbol = next(
                        item
                        for item in second_file.symbols
                        if isinstance(item, FunctionSymbol)
                    )

                    self.assertEqual(first_symbol.id, repeated_symbol.id)
                    self.assertNotEqual(first_symbol.id, second_symbol.id)
                    self.assertEqual(Linkage.INTERNAL, first_symbol.linkage)

    def test_extracts_named_aggregate_types_and_typedefs(self) -> None:
        source = (
            "struct Device;\n"
            "struct Record { int value; };\n"
            "union Payload { int number; unsigned char bytes[4]; };\n"
            "enum State { STATE_IDLE, STATE_READY };\n"
            "typedef unsigned long Counter;\n"
            "typedef struct Record RecordAlias;\n"
            "typedef void (*Callback)(int value);\n"
        )
        with self._parse(source, suffix=".h") as result:
            types = [
                item for item in result.symbols if isinstance(item, TypeSymbol)
            ]
            keys = {(item.type_kind, item.name): item for item in types}

            self.assertFalse(keys[("struct", "Device")].is_definition)
            self.assertTrue(keys[("struct", "Record")].is_definition)
            self.assertTrue(keys[("union", "Payload")].is_definition)
            self.assertTrue(keys[("enum", "State")].is_definition)
            self.assertEqual("unsigned long", keys[("typedef", "Counter")].underlying_type)
            self.assertIn(("typedef", "RecordAlias"), keys)
            self.assertIn(("typedef", "Callback"), keys)

    def test_extracts_file_scope_variables_and_extern_declarations(self) -> None:
        source = (
            "extern volatile unsigned long g_events;\n"
            "static int local_state = 3;\n"
            "const char *application_name = \"fixture\";\n"
            "int function(void) { int local = 0; return local; }\n"
        )
        with self._parse(source) as result:
            variables = {
                item.name: item
                for item in result.symbols
                if isinstance(item, VariableSymbol)
            }

            self.assertEqual(
                {"g_events", "local_state", "application_name"}, set(variables)
            )
            self.assertFalse(variables["g_events"].is_definition)
            self.assertEqual(
                "volatile unsigned long", variables["g_events"].type_spelling
            )
            self.assertEqual(Linkage.INTERNAL, variables["local_state"].linkage)
            self.assertTrue(variables["local_state"].is_definition)
            self.assertNotIn("local", variables)

    def test_reports_ambiguous_and_unsupported_syntax_without_inventing_symbols(self) -> None:
        source = (
            "#if ENABLE_FEATURE\n"
            "int first, second;\n"
            "#endif\n"
            "void (*handler)(int value);\n"
            '"unterminated\n'
        )
        with self._parse(source) as result:
            names = {item.name for item in result.symbols}
            messages = {item.message for item in result.diagnostics}

            self.assertEqual(SourceAnalysisStatus.DEGRADED, result.status)
            self.assertNotIn("first", names)
            self.assertNotIn("second", names)
            self.assertNotIn("handler", names)
            self.assertTrue(result.diagnostics)
            self.assertEqual({"CI-PARSE-001"}, {item.code for item in result.diagnostics})
            self.assertTrue(
                any("Conditional preprocessing" in message for message in messages)
            )
            self.assertTrue(any("Function-pointer" in message for message in messages))
            self.assertTrue(any("Unterminated string" in message for message in messages))
            for diagnostic in result.diagnostics:
                result_path = diagnostic.related_paths[0]
                self.assertTrue(Path(result_path).is_absolute())

    def test_extracts_call_candidates_and_global_usage_from_function_bodies(self) -> None:
        source = (
            "int g_counter;\n"
            "static int helper(int value) { return value + 1; }\n"
            "int run(int input)\n"
            "{\n"
            "    if (input > 0) { return helper(input); }\n"
            "    while (g_counter < 3) { g_counter = helper(g_counter); }\n"
            "    return sizeof(int);\n"
            "}\n"
        )
        with self._parse(source) as result:
            functions = {
                item.name: item
                for item in result.symbols
                if isinstance(item, FunctionSymbol)
            }
            calls = [
                item
                for item in result.relationships
                if isinstance(item, CallRelationship)
            ]
            usages = [
                item
                for item in result.relationships
                if isinstance(item, GlobalUsageRelationship)
            ]

            self.assertEqual(
                RelationshipResolution.UNRESOLVED,
                calls[0].resolution,
            )
            callees = {item.callee_spelling for item in calls}
            self.assertIn("helper", callees)
            self.assertNotIn("if", callees)
            self.assertNotIn("while", callees)
            self.assertNotIn("sizeof", callees)
            self.assertNotIn("return", callees)
            function_ids = {item.id for item in functions.values()}
            for call in calls:
                self.assertIn(call.caller_id, function_ids)
                self.assertIsNotNone(call.evidence)
            self.assertEqual({"g_counter"}, {item.variable_spelling for item in usages})
            run_id = next(
                item.id
                for item in result.symbols
                if isinstance(item, FunctionSymbol) and item.name == "run"
            )
            for usage in usages:
                self.assertEqual(run_id, usage.function_id)
                self.assertIsNotNone(usage.variable_id)

    def test_member_access_is_not_a_direct_call_candidate(self) -> None:
        source = (
            "struct config { int (*apply)(int); };\n"
            "void drive(struct config *config) { config->apply(1); }\n"
        )
        with self._parse(source) as result:
            calls = [
                item
                for item in result.relationships
                if isinstance(item, CallRelationship)
            ]
            self.assertEqual([], [item for item in calls if item.callee_spelling == "apply"])

    def _parse(self, source: str, suffix: str = ".c", file_id: str = "file-sample"):
        return _ParsedSource(source, suffix, file_id)


class _ParsedSource:
    def __init__(self, source: str, suffix: str, file_id: str) -> None:
        self._source = source
        self._suffix = suffix
        self._file_id = file_id
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self):
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        path = root / f"sample{self._suffix}"
        path.write_text(self._source, encoding="utf-8")
        repository_file = RepositoryFile(
            id=self._file_id,
            repository_id="repository-1",
            relative_path=path.name,
            absolute_path=str(path),
            kind=FileKind.C_HEADER if self._suffix == ".h" else FileKind.C_SOURCE,
            size=path.stat().st_size,
            modified_at=datetime.now(timezone.utc),
            content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        return ConservativeCSourceParser().parse(repository_file, None)

    def __exit__(self, exc_type, exc_value, traceback):
        assert self._temporary is not None
        self._temporary.cleanup()
