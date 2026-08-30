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

echo "Using interpreter: $PYTHON ($("$PYTHON" --version))"

# ---------------------------------------------------------------------------
# 2. Create or reuse the virtual environment
# ---------------------------------------------------------------------------
section "Setting up virtual environment"

if [[ -x "$VENV_DIR/bin/python" ]] && python_ok "$VENV_DIR/bin/python"; then
    echo "Reusing existing virtualenv at $VENV_DIR"
else
    if [[ -e "$VENV_DIR" ]]; then
        echo "Removing broken virtualenv at $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi
    "$PYTHON" -m venv "$VENV_DIR"
    echo "Created virtualenv at $VENV_DIR"
fi

# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"
PYTHON="$VENV_DIR/bin/python"

# ---------------------------------------------------------------------------
# 3. Install the project (skipped automatically when already current)
# ---------------------------------------------------------------------------
section "Installing cintel"

"$PYTHON" "$PROJECT_ROOT/scripts/install.py"

echo
echo "cintel is installed:"
"$PYTHON" -m cintel --help | head -n 3

# ---------------------------------------------------------------------------
# 4. Optional test run
# ---------------------------------------------------------------------------
section "Test suite"

read -r -p "Run the test suite to verify the install? [y/N]: " run_tests
if [[ "${run_tests:-}" =~ ^[Yy] ]]; then
    (cd "$PROJECT_ROOT" && PYTHONPATH=src "$PYTHON" -m unittest discover -s tests)
fi

# ---------------------------------------------------------------------------
# 5. Guided first analysis
# ---------------------------------------------------------------------------
section "Guided first analysis"

echo "Choose a legacy C repository to analyze."
echo "A demo fixture is available at:"
echo "  $PROJECT_ROOT/tests/fixtures/complex_c_project"
echo
prompt_value "Repository path" "$PROJECT_ROOT/tests/fixtures/complex_c_project"
REPO="${REPLY/#\~/$HOME}"
REPO="$(cd "$REPO" && pwd)"

if [[ ! -d "$REPO" ]]; then
    echo "error: $REPO is not a directory." >&2
    exit 1
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

BUILD_CONFIG="debug"

echo
echo "Build evidence for analysis:"
echo "  1) Live Make dry-run   - run 'make -n' inside the repository now"
echo "  2) Imported input file - validate a saved dry-run/build log and resume"
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
        prompt_value "Make target" "all"
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
        echo "Warning: 'make -n' may evaluate \$(shell ...) expressions."
        echo "cintel will show the exact command and ask for confirmation."
        echo
        MAKE_ARGS=(--makefile "$MAKEFILE" --target "$TARGET" --build-config "$BUILD_CONFIG")
        for var in "${MAKE_VARS[@]+"${MAKE_VARS[@]}"}"; do
            MAKE_ARGS+=(--make-var "$var")
        done
        ANALYZE_WITH_BUILD=true
        discovery_output="$("$PYTHON" -m cintel --repository "$REPO" "${MAKE_ARGS[@]}" build discover 2>&1)" || {
            echo "$discovery_output"
            exit 1
        }
        echo "$discovery_output"
        if grep -q "^Compiler invocations: 0" <<<"$discovery_output"; then
            echo
            echo "hint: no compiler commands were found. The target may not exist."
            echo "      Try another target, e.g.: make -n -f $MAKEFILE <target>"
            echo "      Saved dry-run text can also be imported via choice 2."
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
        prompt_value "Input type" "make_dry_run"
        INPUT_TYPE="$REPLY"
        echo
        MAKE_ARGS=(--build-config "$BUILD_CONFIG" --input-file "$INPUT_FILE" --input-type "$INPUT_TYPE")
        "$PYTHON" -m cintel --repository "$REPO" resume "${MAKE_ARGS[@]}"
        ANALYZE_WITH_BUILD=true
        ;;
    3)
        echo "Skipping build evidence; analysis will be file-scoped."
        ;;
    *)
        echo "Unknown choice '$EVIDENCE'; skipping build evidence." >&2
        ;;
esac

"$PYTHON" -m cintel --repository "$REPO" --build-config "$BUILD_CONFIG" analyze

# ---------------------------------------------------------------------------
# 6. Wrap-up
# ---------------------------------------------------------------------------
section "Done"

echo "Generated state: $REPO/.code-intelligence/"
echo
echo "Next steps:"
if $ANALYZE_WITH_BUILD; then
    echo "  cintel --repository $REPO --build-config $BUILD_CONFIG build units"
    echo "  cintel --repository $REPO --build-config $BUILD_CONFIG build show src/some_file.c"
else
    echo "  Re-run with Make evidence to get build-aware analysis:"
    echo "    ./start.sh   (choose option 1)"
fi
echo "  cat $REPO/.code-intelligence/REQUIRED_INPUTS.md   # missing-evidence guidance"
echo
echo "To activate the environment in your shell:"
echo "  . $VENV_DIR/bin/activate"
