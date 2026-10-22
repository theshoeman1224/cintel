#!/usr/bin/env bash
#
# start.sh - one-command setup and first run for cintel.
#
# Sets up a Python virtual environment, installs the project, optionally
# runs the test suite, then walks through a first analysis of a C
# repository. Fully re-runnable: existing state is reused where valid.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }

section() {
    printf '\n'
    bold "=== $* ==="
}

prompt_value() {
    # prompt_value PROMPT DEFAULT -> reply in global REPLY
    local prompt="$1" default="${2:-}"
    if [[ -n "$default" ]]; then
        read -r -p "$prompt [$default]: " REPLY
        REPLY="${REPLY:-$default}"
    else
        read -r -p "$prompt: " REPLY
    fi
}

python_ok() {
    "$1" - <<'EOF' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
EOF
}

venv_ok() {
    # A venv is reusable only when its interpreter runs and its pip works.
    # A system Python upgrade can leave a stale interpreter with missing pip.
    [[ -x "$1/bin/python" ]] \
        && python_ok "$1/bin/python" \
        && "$1/bin/python" -m pip --version >/dev/null 2>&1
}

resolve_repository() {
    # resolve_repository PATH -> absolute directory on stdout, or an error
    # on stderr and status 1. A leading ~ expands to $HOME.
    local path="${1/#\~/$HOME}"
    if [[ -z "$path" || ! -d "$path" ]]; then
        echo "error: '$path' is not a directory." >&2
        return 1
    fi
    (cd "$path" && pwd)
}

prepare_demo_copy() {
    # prepare_demo_copy FIXTURE DEST -> make DEST a disposable copy of the
    # demo fixture, so the committed fixture is never written to. An
    # existing copy is reused with its workspace and analysis state.
    local fixture="$1" dest="$2"
    if [[ -d "$dest" ]]; then
        echo "Reusing demo copy at $dest"
        return 0
    fi
    "${PYTHON:-python3}" - "$fixture" "$dest" <<'EOF'
import shutil
import sys
from pathlib import Path

source, destination = Path(sys.argv[1]), Path(sys.argv[2])
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(
    source,
    destination,
    ignore=shutil.ignore_patterns(".code-intelligence", "build", "__pycache__"),
)
# Generated outputs are rebuilt with `make generate`, never copied.
generated = destination / "generated"
if generated.is_dir():
    for item in generated.iterdir():
        if item.name != ".gitkeep":
            item.unlink()
EOF
    echo "Copied the demo fixture to $dest"
    if command -v make >/dev/null 2>&1; then
        if make -s -C "$dest" generate CONFIG=linux >/dev/null 2>&1; then
            echo "Generated the demo's build inputs (make generate CONFIG=linux)."
        else
            echo "warning: make generate failed; analysis will report missing generated inputs." >&2
        fi
    fi
}

# Sourcing the script (as the tests do) loads the helpers above without
# running the setup below.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

# ---------------------------------------------------------------------------
# 1. Find a suitable Python interpreter
# ---------------------------------------------------------------------------
section "Checking Python (3.11 or newer required)"

PYTHON=""
for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "error: no Python 3.11+ interpreter found on PATH." >&2
    echo "Install Python 3.11 or newer and re-run this script." >&2
    exit 1
fi

echo "Found interpreter: $PYTHON ($("$PYTHON" --version))"

# ---------------------------------------------------------------------------
# 2. Create or reuse the virtual environment
# ---------------------------------------------------------------------------
section "Setting up virtual environment"

if venv_ok "$VENV_DIR"; then
    echo "Reusing existing virtualenv at $VENV_DIR"
else
    if [[ -e "$VENV_DIR" ]]; then
        echo "Removing unusable virtualenv at $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi
    "$PYTHON" -m venv "$VENV_DIR"
    echo "Created virtualenv at $VENV_DIR"
fi

# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"
PYTHON="$VENV_DIR/bin/python"
# A reused virtualenv keeps the Python it was created with.
echo "Virtualenv interpreter: $("$PYTHON" --version)"

# ---------------------------------------------------------------------------
# 3. Install the project (skipped automatically when already current)
# ---------------------------------------------------------------------------
section "Installing cintel"

"$PYTHON" "$PROJECT_ROOT/scripts/install.py"

echo
echo "cintel is installed:"
help_output="$("$PYTHON" -m cintel --help)"
head -n 3 <<<"$help_output"

# ---------------------------------------------------------------------------
# 4. Optional test run
# ---------------------------------------------------------------------------
section "Test suite"

read -r -p "Run the test suite to verify the install? [y/N]: " run_tests
if [[ "${run_tests:-}" =~ ^[Yy] ]]; then
    # Redirect stdin so the suite can never block on the caller's terminal.
    (cd "$PROJECT_ROOT" && PYTHONPATH=src "$PYTHON" -m unittest discover -s tests < /dev/null)
fi

# ---------------------------------------------------------------------------
# 5. Guided first analysis
# ---------------------------------------------------------------------------
section "Guided first analysis"

DEMO_FIXTURE="$PROJECT_ROOT/tests/fixtures/complex_c_project"
DEMO_COPY="$PROJECT_ROOT/.fixture-output/demo/complex_c_project"

echo "Choose a legacy C repository to analyze."
echo "A demo fixture is available at:"
echo "  $DEMO_FIXTURE"
echo "Choosing it analyzes a disposable copy under .fixture-output/demo/."
echo
while true; do
    prompt_value "Repository path" "$DEMO_FIXTURE"
    if REPO="$(resolve_repository "$REPLY")"; then
        break
    fi
    echo "Enter an existing directory, or press Ctrl-C to quit."
done

if [[ "$REPO" == "$DEMO_FIXTURE" ]]; then
    prepare_demo_copy "$DEMO_FIXTURE" "$DEMO_COPY"
    REPO="$DEMO_COPY"
fi

echo
echo "Plan:"
echo "  1. init   - create $REPO/.code-intelligence (skipped if present)"
echo "  2. doctor - inspect tools, inputs, and capabilities"
echo "  3. scan   - inventory C sources, headers, and build inputs"
echo "  4. build evidence (optional) and analyze"
echo

if [[ -f "$REPO/.code-intelligence/config.toml" ]]; then
    echo "Workspace already exists at $REPO/.code-intelligence; skipping init."
else
    "$PYTHON" -m cintel init "$REPO"
fi

"$PYTHON" -m cintel --repository "$REPO" doctor
"$PYTHON" -m cintel --repository "$REPO" scan

echo
echo "Assessing missing build evidence (cintel setup)..."
setup_output="$("$PYTHON" -m cintel --repository "$REPO" setup 2>&1)" \
    && SETUP_BLOCKED=false || SETUP_BLOCKED=true
echo "$setup_output"
if [[ "$SETUP_BLOCKED" == true ]] \
    || { [[ "$setup_output" != "" ]] && grep -q "^\[" <<<"$setup_output"; }; then
    echo
    echo "Note: setup reports missing build evidence; see"
    echo "  $REPO/.code-intelligence/REQUIRED_INPUTS.md"
fi

BUILD_CONFIG="debug"

echo
echo "Build evidence for analysis:"
echo "  1) Live Make dry-run   - run 'make -n' inside the repository now"
echo "  2) Imported dry-run    - validate saved 'make -n' output and resume"
echo "  3) Skip                - analyze file-scoped without build evidence"
echo
prompt_value "Choose evidence source (1/2/3)" "3"
EVIDENCE="$REPLY"

MAKE_ARGS=()
ANALYZE_WITH_BUILD=false

case "$EVIDENCE" in
    1)
        prompt_value "Makefile (relative to repository)" "Makefile"
        MAKEFILE="$REPLY"
        prompt_value "Make target (blank uses the Makefile default goal)" ""
        TARGET="$REPLY"
        prompt_value "Build configuration name" "$BUILD_CONFIG"
        BUILD_CONFIG="$REPLY"
        MAKE_VARS=()
        while true; do
            prompt_value "Make variable NAME=value (blank to finish)" ""
            [[ -z "$REPLY" ]] && break
            MAKE_VARS+=("$REPLY")
        done
        echo
        echo "Evaluated command (read-only; sets no variables):"
        make_eval_args=(-n -B -f "$MAKEFILE")
        if [[ -n "$TARGET" ]]; then
            make_eval_args+=("$TARGET")
        fi
        for var in "${MAKE_VARS[@]+"${MAKE_VARS[@]}"}"; do
            make_eval_args+=("$var")
        done
        echo "  make ${make_eval_args[*]}"
        echo
        echo "Warning: 'make -n' may evaluate \$(shell ...) expressions."
        prompt_value "Proceed with Makefile evaluation? [y/N]" "n"
        if [[ ! "$REPLY" =~ ^[Yy] ]]; then
            echo
            echo "Build discovery skipped; analysis will be file-scoped."
            echo "Re-run later with choice 1 or import saved evidence with choice 2."
        else
            MAKE_ARGS=(
                --makefile "$MAKEFILE"
                --build-config "$BUILD_CONFIG" --non-interactive
            )
            if [[ -n "$TARGET" ]]; then
                MAKE_ARGS+=(--target "$TARGET")
            fi
            for var in "${MAKE_VARS[@]+"${MAKE_VARS[@]}"}"; do
                MAKE_ARGS+=(--make-var "$var")
            done
            ANALYZE_WITH_BUILD=true
            if ! discovery_output="$("$PYTHON" -m cintel --repository "$REPO" \
                "${MAKE_ARGS[@]}" build discover 2>&1)"; then
                echo "$discovery_output" >&2
                echo
                echo "Build discovery failed; continuing with file-scoped analysis."
                ANALYZE_WITH_BUILD=false
            else
                echo "$discovery_output"
                if grep -qE "^Compiler invocations: 0|^Compilation units: 0" <<<"$discovery_output"; then
                    echo
                    echo "hint: no compilation units were found; analysis will be file-scoped."
                    echo "      The target may not exist. Try: make -n -B -f $MAKEFILE <target>"
                    echo "      Saved dry-run text can also be imported via choice 2."
                    ANALYZE_WITH_BUILD=false
                fi
            fi
        fi
        ;;
    2)
        prompt_value "Input file path" ""
        INPUT_FILE="${REPLY/#\~/$HOME}"
        if [[ ! -f "$INPUT_FILE" ]]; then
            echo "error: $INPUT_FILE is not a file." >&2
            exit 1
        fi
        echo "Input types: make_dry_run, build_log, file_list,"
        echo "             dependency_file, preprocessed_source, macro_listing"
        echo "Only make_dry_run evidence enables build-aware analysis today; the"
        echo "other types are validated and kept for future compiler enrichment."
        prompt_value "Input type" "make_dry_run"
        INPUT_TYPE="$REPLY"
        prompt_value "Build configuration name" "$BUILD_CONFIG"
        BUILD_CONFIG="$REPLY"
        prompt_value "Makefile the evidence came from (relative to repository)" "Makefile"
        MAKEFILE="$REPLY"
        prompt_value "Make target the evidence came from (blank for the default goal)" ""
        TARGET="$REPLY"
        echo
        MAKE_ARGS=(
            --build-config "$BUILD_CONFIG" --makefile "$MAKEFILE"
            --input-file "$INPUT_FILE" --input-type "$INPUT_TYPE"
        )
        if [[ -n "$TARGET" ]]; then
            MAKE_ARGS+=(--target "$TARGET")
        fi
        if [[ "$INPUT_TYPE" != "make_dry_run" ]]; then
            echo "Note: $INPUT_TYPE evidence is recorded but not used by analysis yet;"
            echo "analysis will be file-scoped."
        fi
        if "$PYTHON" -m cintel --repository "$REPO" "${MAKE_ARGS[@]}" resume; then
            if [[ "$INPUT_TYPE" == "make_dry_run" ]]; then
                ANALYZE_WITH_BUILD=true
            fi
        else
            echo
            echo "Evidence import failed; continuing with file-scoped analysis."
            echo "Fix the input and re-run, or choose option 1 on a machine with Make."
        fi
        ;;
    3)
        echo "Skipping build evidence; analysis will be file-scoped."
        ;;
    *)
        echo "Unknown choice '$EVIDENCE'; skipping build evidence." >&2
        ;;
esac

if [[ "$ANALYZE_WITH_BUILD" == true ]]; then
    UNITS_STATUS=0
    units_output="$("$PYTHON" -m cintel --repository "$REPO" \
        --build-config "$BUILD_CONFIG" build units 2>&1)" || UNITS_STATUS=$?
    if [[ "$UNITS_STATUS" != 0 ]] \
        || grep -q "No compilation units found" <<<"$units_output"; then
        echo
        echo "No compilation units are available from the supplied evidence;"
        echo "continuing with file-scoped analysis."
        ANALYZE_WITH_BUILD=false
    fi
fi

ANALYZE_ARGS=(--repository "$REPO")
if [[ "$ANALYZE_WITH_BUILD" == true ]]; then
    ANALYZE_ARGS+=(--build-config "$BUILD_CONFIG")
fi

ANALYZE_STATUS=0
analyze_output="$("$PYTHON" -m cintel "${ANALYZE_ARGS[@]}" analyze 2>&1)" \
    || ANALYZE_STATUS=$?
echo "$analyze_output"
if [[ "$ANALYZE_STATUS" != 0 ]]; then
    echo "warning: cintel analyze exited with status $ANALYZE_STATUS." >&2
fi

echo
echo "Regenerating reports (cintel report)..."
REPORT_STATUS=0
report_output="$("$PYTHON" -m cintel --repository "$REPO" report 2>&1)" \
    || REPORT_STATUS=$?
echo "$report_output"
if [[ "$REPORT_STATUS" != 0 ]]; then
    echo "warning: cintel report exited with status $REPORT_STATUS." >&2
fi

# ---------------------------------------------------------------------------
# 6. Wrap-up
# ---------------------------------------------------------------------------
section "Done"

echo "Generated state: $REPO/.code-intelligence/"
echo
echo "Findings:"
if [[ "$analyze_output" != "" ]] && grep -q "^\[" <<<"$analyze_output"; then
    echo "Diagnostics reported during analysis:"
    grep "^\[" <<<"$analyze_output" | sed 's/^/  /'
    echo
    echo "Full index: $REPO/.code-intelligence/reports/diagnostics_index.md"
    echo
fi
echo "  Diagnostics:        reports/diagnostics_index.md"
echo "  Includes (resolved/unresolved): reports/include_index.md"
echo "  Call graph:         reports/call_graph.md"
echo "  Missing-evidence guidance: REQUIRED_INPUTS.md"
echo
echo "Next steps:"
if $ANALYZE_WITH_BUILD; then
    echo "  cintel --repository \"$REPO\" --build-config \"$BUILD_CONFIG\" build units"
    echo "  cintel --repository \"$REPO\" --build-config \"$BUILD_CONFIG\" build show src/some_file.c"
else
    echo "  cintel --repository \"$REPO\" symbols"
    echo "  cintel --repository \"$REPO\" show function <name>"
    echo "  Re-run with Make evidence that produces compilation units to get"
    echo "  build-aware queries:"
    echo "    ./start.sh   (choose option 1 or 2)"
fi
echo "  cat \"$REPO/.code-intelligence/REQUIRED_INPUTS.md\"   # missing-evidence guidance"
echo
echo "To activate the environment in your shell:"
echo "  . $VENV_DIR/bin/activate"
if [[ "$ANALYZE_STATUS" != 0 || "$REPORT_STATUS" != 0 ]]; then
    exit 1
fi
