"""Build configurations, discovery runs, and compilation units."""

from __future__ import annotations

import json
from dataclasses import asdict

from cintel.adapters.storage.serialization import (
    build_configuration_from_dict,
    build_result_from_dict,
    compilation_unit_from_dict,
    redact_text,
    sanitized_json,
)
from cintel.adapters.storage.sqlite.base import StoreBase
from cintel.domain.models import (
    BuildConfiguration,
    BuildDiscoveryResult,
    CompilationUnit,
)


class BuildStore(StoreBase):

    """Build configurations, discovery runs, and compilation units."""
    def save_build_discovery(self, result: BuildDiscoveryResult) -> None:
        """Persist a run with its configuration, invocations, units, and commands."""
        connection = self._connect()
        configuration_payload = sanitized_json(
            asdict(result.configuration), result.configuration
        )
        result_payload = sanitized_json(asdict(result), result.configuration)
        connection.execute(
            """
            INSERT INTO build_configurations
              (id, repository_id, name, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              payload=excluded.payload
            """,
            (
                result.configuration.id,
                result.configuration.repository_id,
                result.configuration.name,
                configuration_payload,
            ),
        )
        connection.execute(
            """
            INSERT INTO build_discovery_runs
              (input_fingerprint, build_configuration_id, build_fingerprint,
               discovered_at, exit_code, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(input_fingerprint) DO UPDATE SET
              build_configuration_id=excluded.build_configuration_id,
              build_fingerprint=excluded.build_fingerprint,
              discovered_at=excluded.discovered_at,
              exit_code=excluded.exit_code,
              payload=excluded.payload
            """,
            (
                result.input_fingerprint,
                result.configuration.id,
                result.build_fingerprint,
                result.discovered_at.isoformat(),
                result.exit_code,
                result_payload,
            ),
        )
        connection.execute(
            "DELETE FROM compiler_invocations WHERE build_configuration_id = ?",
            (result.configuration.id,),
        )
        connection.execute(
            "DELETE FROM compilation_units WHERE build_configuration_id = ?",
            (result.configuration.id,),
        )
        connection.execute(
            "DELETE FROM build_commands WHERE build_configuration_id = ?",
            (result.configuration.id,),
        )
        connection.executemany(
            """
            INSERT INTO compiler_invocations
              (id, build_configuration_id, working_directory, source_path, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    item.id,
                    result.configuration.id,
                    item.working_directory,
                    item.source.absolute if item.source else None,
                    sanitized_json(asdict(item), result.configuration),
                )
                for item in result.compiler_invocations
            ),
        )
        connection.executemany(
            """
            INSERT INTO compilation_units
              (id, repository_id, build_configuration_id, source_file_id,
               fingerprint, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    item.id,
                    item.repository_id,
                    item.build_configuration_id,
                    item.source_file_id,
                    item.fingerprint,
                    sanitized_json(asdict(item), result.configuration),
                )
                for item in result.compilation_units
            ),
        )
        connection.executemany(
            """
            INSERT INTO build_commands
              (build_configuration_id, sequence, working_directory,
               classification, raw_content, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    result.configuration.id,
                    sequence,
                    item.working_directory,
                    item.classification,
                    redact_text(item.raw_content, result.configuration),
                    sanitized_json(asdict(item), result.configuration),
                )
                for sequence, item in enumerate(result.commands)
            ),
        )
        connection.commit()

    def get_cached_build_discovery(
        self, input_fingerprint: str
    ) -> BuildDiscoveryResult | None:
        """Result whose input fingerprint matches, or None."""
        row = self._connect().execute(
            "SELECT payload FROM build_discovery_runs WHERE input_fingerprint = ?",
            (input_fingerprint,),
        ).fetchone()
        return build_result_from_dict(json.loads(row[0])) if row else None

    def list_build_configurations(
        self, repository_id: str
    ) -> tuple[BuildConfiguration, ...]:
        """Configurations ordered by name and id."""
        rows = self._connect().execute(
            """
            SELECT payload FROM build_configurations
            WHERE repository_id = ?
            ORDER BY name, id
            """,
            (repository_id,),
        ).fetchall()
        return tuple(build_configuration_from_dict(json.loads(row[0])) for row in rows)

    def list_compilation_units(
        self, repository_id: str, build_configuration_name: str | None = None
    ) -> tuple[CompilationUnit, ...]:
        """Units, optionally filtered by configuration name."""
        arguments: list[str] = [repository_id]
        query = """
            SELECT units.payload
            FROM compilation_units AS units
            JOIN build_configurations AS configurations
              ON configurations.id = units.build_configuration_id
            WHERE units.repository_id = ?
        """
        if build_configuration_name is not None:
            query += " AND configurations.name = ?"
            arguments.append(build_configuration_name)
        query += " ORDER BY configurations.name, units.id"
        rows = self._connect().execute(query, tuple(arguments)).fetchall()
        return tuple(compilation_unit_from_dict(json.loads(row[0])) for row in rows)
