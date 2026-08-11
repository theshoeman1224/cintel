# Architecture

## Overview

Legacy C Code Intelligence uses a ports-and-adapters design so build-system,
compiler, persistence, and presentation concerns remain outside the domain.
The deterministic analysis path is local and does not depend on an AI model or
external service.

```text
CLI and TOML configuration
          |
          v
Application services and composition root
          |
          v
Domain models and protocol-based ports
          |
          v
Filesystem | GNU Make | compiler parser | SQLite | reports
          |
          v
Repository-local .code-intelligence workspace
```

## Main Components

- `domain` defines immutable repositories, files, build configurations,
  compilation units, symbols, relationships, capabilities, artifacts, workflow
  state, and diagnostics.
- `application` coordinates initialization, environment checks, repository
  scanning, build discovery, and guided recovery without embedding adapter
  details.
- `ports` defines contracts for command execution, build discovery, compiler
  handling, source parsing, storage, rendering, artifacts, guidance, and
  optional AI integration.
- `adapters` provides filesystem discovery, GNU Make evaluation, GCC-style
  argument normalization, conservative C parsing, SQLite persistence,
  Markdown/JSON reports, and isolated subprocess execution.
- `composition.py` constructs dependencies explicitly; the project does not use
  global service instances.

## Data Flow

Repository scanning discovers C, header, Makefile, and Make fragment inputs,
applies exclusions, computes SHA-256 hashes, and reuses stored hashes when file
metadata is unchanged. The resulting inventory and diagnostics are persisted
and rendered as Markdown and JSON.

Build discovery asks GNU Make for a dry run, or consumes a validated saved dry
run when Make is unavailable. The adapter tracks recursive working directories,
splits shell command sequences, recognizes compiler wrappers, and sends
candidate invocations through a GCC-style argument parser. Normalized commands,
compiler flags, selected and missing sources, compilation units, raw evidence,
and fingerprints are stored in SQLite.

Guided recovery converts missing capabilities into concrete instructions rather
than failing the whole workflow. Imported artifacts are copied, hashed,
validated, associated with a build configuration, checked for staleness, and
used to resume persisted workflow stages.

The source-parser foundation masks comments and literals while preserving byte
offsets, then conservatively extracts includes, macros, declarations,
definitions, named types, typedefs, and file-scope variables. Parser results can
be persisted with confidence and diagnostics, but application orchestration and
cross-file relationship resolution are not yet exposed through the CLI.

## Design Decisions

- GNU Make remains the source of truth for includes, functions, recursion, and
  variable expansion; the project interprets evaluated evidence rather than
  attempting a partial Make parser.
- Stable source, build, and configuration fingerprints preserve separate
  compilation contexts and enable cache reuse.
- Missing tools and inputs reduce reported capabilities instead of disabling
  repository-level analysis.
- Commands use argument lists with `shell=False`, and subprocess access is
  isolated behind one adapter.
- Uncertain C constructs remain explicit through confidence, evidence, and
  structured diagnostics rather than being presented as resolved facts.

## Testing

The standard-library `unittest` suite covers command safety, repository hashing,
configuration, Make parsing, compiler argument normalization, artifact
validation, secret redaction, parser behavior, SQLite migrations, caching, and
CLI workflows. Integration tests use a representative multi-configuration C
fixture with recursive Make, generated inputs, wrapper commands, and saved
dry-run evidence; live Make/GCC coverage is conditional on those tools being
available.
