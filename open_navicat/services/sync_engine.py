"""Schema and Data Synchronization Engine.

Compares two databases (or two connections), detects structural differences,
generates DDL scripts, and optionally executes them on the target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from open_navicat.models.table_schema import ColumnInfo, ForeignKeyInfo, IndexInfo, TableInfo
from open_navicat.services.metadata_service import metadata_service
from open_navicat.utils.sql_generator import _column_sql, generate_create_table

# ── Diff data models ──────────────────────────────────────────────────────


@dataclass
class ColumnDiff:
    """Difference of a single column between source and target."""
    column_name: str
    old_type: str = ""
    new_type: str = ""
    old_nullable: bool = True
    new_nullable: bool = True
    old_default: str = ""
    new_default: str = ""
    source_column: Optional[ColumnInfo] = None


@dataclass
class IndexDiff:
    """Difference of a single index."""
    index_name: str
    action: str = "add"  # add | remove | modify


@dataclass
class ForeignKeyDiff:
    """Difference of a single foreign key."""
    fk_name: str
    action: str = "add"  # add | remove


@dataclass
class TableDiff:
    """Differences found in a single table."""
    table_name: str
    added_columns: list[ColumnInfo] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    modified_columns: list[ColumnDiff] = field(default_factory=list)
    added_indexes: list[IndexInfo] = field(default_factory=list)
    removed_indexes: list[str] = field(default_factory=list)
    added_foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    removed_foreign_keys: list[str] = field(default_factory=list)


@dataclass
class SyncDiff:
    """Complete comparison result between two databases."""
    source_db: str = ""
    target_db: str = ""
    added_tables: list[TableInfo] = field(default_factory=list)
    removed_tables: list[str] = field(default_factory=list)
    modified_tables: list[TableDiff] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        count = len(self.added_tables) + len(self.removed_tables) + len(self.modified_tables)
        for td in self.modified_tables:
            count += (len(td.added_columns) + len(td.removed_columns) +
                      len(td.modified_columns) + len(td.added_indexes) +
                      len(td.removed_indexes) + len(td.added_foreign_keys) +
                      len(td.removed_foreign_keys))
        return count

    @property
    def has_changes(self) -> bool:
        return self.total_changes > 0


# ── Sync Engine ───────────────────────────────────────────────────────────


class SyncEngine:
    """Compares database schemas and generates synchronization scripts."""

    def compare_databases(
        self,
        connection_id: str,
        source_db: str,
        target_db: str,
        target_connection_id: Optional[str] = None,
    ) -> SyncDiff:
        """Compare two databases on (possibly) two connections."""
        tcid = target_connection_id or connection_id
        diff = SyncDiff(source_db=source_db, target_db=target_db)

        # Get table lists
        src_tables = set(metadata_service.list_tables(connection_id, source_db))
        tgt_tables = set(metadata_service.list_tables(tcid, target_db))

        # Tables only in source → added
        for t in sorted(src_tables - tgt_tables):
            info = metadata_service.get_table_info(connection_id, source_db, t)
            if info:
                info.database = target_db
                diff.added_tables.append(info)

        # Tables only in target → removed
        diff.removed_tables = sorted(tgt_tables - src_tables)

        # Common tables → deep compare
        for t in sorted(src_tables & tgt_tables):
            src_info = metadata_service.get_table_info(connection_id, source_db, t)
            tgt_info = metadata_service.get_table_info(tcid, target_db, t)
            if src_info and tgt_info:
                td = self._compare_table(src_info, tgt_info)
                if td is not None:
                    diff.modified_tables.append(td)

        return diff

    def _compare_table(self, src: TableInfo, tgt: TableInfo) -> Optional[TableDiff]:
        """Deep-compare two TableInfo objects, return TableDiff or None."""
        td = TableDiff(table_name=src.name)

        src_cols = {c.name: c for c in src.columns}
        tgt_cols = {c.name: c for c in tgt.columns}

        src_col_names = set(src_cols.keys())
        tgt_col_names = set(tgt_cols.keys())

        # Added columns
        for name in sorted(src_col_names - tgt_col_names):
            td.added_columns.append(src_cols[name])

        # Removed columns
        td.removed_columns = sorted(tgt_col_names - src_col_names)

        # Modified columns
        for name in sorted(src_col_names & tgt_col_names):
            sc = src_cols[name]
            tc = tgt_cols[name]
            if self._column_changed(sc, tc):
                td.modified_columns.append(ColumnDiff(
                    column_name=name,
                    old_type=tc.data_type,
                    new_type=sc.data_type,
                    old_nullable=tc.nullable,
                    new_nullable=sc.nullable,
                    source_column=sc,
                ))

        # Indexes
        src_idx = {i.name: i for i in src.indexes}
        tgt_idx = {i.name: i for i in tgt.indexes}
        src_idx_names = set(src_idx.keys())
        tgt_idx_names = set(tgt_idx.keys())
        for name in sorted(src_idx_names - tgt_idx_names):
            td.added_indexes.append(src_idx[name])
        td.removed_indexes = sorted(tgt_idx_names - src_idx_names)

        # Foreign keys
        src_fk = {f.name: f for f in src.foreign_keys}
        tgt_fk = {f.name: f for f in tgt.foreign_keys}
        src_fk_names = set(src_fk.keys())
        tgt_fk_names = set(tgt_fk.keys())
        for name in sorted(src_fk_names - tgt_fk_names):
            td.added_foreign_keys.append(src_fk[name])
        td.removed_foreign_keys = sorted(tgt_fk_names - src_fk_names)

        # Return None if nothing changed
        if (not td.added_columns and not td.removed_columns and not td.modified_columns
                and not td.added_indexes and not td.removed_indexes
                and not td.added_foreign_keys and not td.removed_foreign_keys):
            return None

        return td

    @staticmethod
    def _column_changed(a: ColumnInfo, b: ColumnInfo) -> bool:
        """Check if two ColumnInfo objects represent a meaningful change."""
        if a.data_type.upper() != b.data_type.upper():
            return True
        if a.nullable != b.nullable:
            return True
        if a.is_primary_key != b.is_primary_key:
            return True
        if a.is_auto_increment != b.is_auto_increment:
            return True
        if a.char_max_length != b.char_max_length:
            return True
        if a.numeric_precision != b.numeric_precision:
            return True
        if a.numeric_scale != b.numeric_scale:
            return True
        return False

    # ── DDL generation ─────────────────────────────────────────────────

    def generate_sync_script(
        self, diff: SyncDiff, target_db: str = "", engine: str = "mysql",
    ) -> list[str]:
        """Generate DDL statements to synchronize target with source.

        Args:
            engine: "mysql" or "postgresql" — controls quoting and DDL syntax.
        """
        is_pg = engine == "postgresql"
        q = '"' if is_pg else "`"
        statements: list[str] = []

        # New tables
        for table in diff.added_tables:
            ddl = generate_create_table(table)
            statements.append(ddl)

        # Removed tables
        for name in diff.removed_tables:
            tn = f"{q}{target_db}{q}.{q}{name}{q}" if target_db else f"{q}{name}{q}"
            statements.append(f"DROP TABLE IF EXISTS {tn};")

        # Modified tables
        for td in diff.modified_tables:
            tn = f"{q}{target_db}{q}.{q}{td.table_name}{q}" if target_db else f"{q}{td.table_name}{q}"

            for col in td.added_columns:
                statements.append(
                    f"ALTER TABLE {tn} ADD COLUMN {_column_sql(col)};"
                )
            for col_name in td.removed_columns:
                statements.append(
                    f"ALTER TABLE {tn} DROP COLUMN {q}{col_name}{q};"
                )
            for cd in td.modified_columns:
                src = cd.source_column
                if src:
                    if is_pg:
                        statements.append(
                            f"ALTER TABLE {tn} ALTER COLUMN {q}{cd.column_name}{q} "
                            f"TYPE {src.data_type};"
                        )
                    else:
                        statements.append(
                            f"ALTER TABLE {tn} MODIFY COLUMN {_column_sql(src)};"
                        )

            for idx in td.added_indexes:
                cols = ", ".join(f"{q}{c}{q}" for c in idx.columns)
                if idx.is_primary:
                    statements.append(
                        f"ALTER TABLE {tn} ADD PRIMARY KEY ({cols});"
                    )
                elif idx.is_unique:
                    statements.append(
                        f"CREATE UNIQUE INDEX {q}{idx.name}{q} ON {tn} ({cols});"
                    )
                else:
                    statements.append(
                        f"CREATE INDEX {q}{idx.name}{q} ON {tn} ({cols});"
                    )
            for idx_name in td.removed_indexes:
                if is_pg:
                    statements.append(f"DROP INDEX {q}{idx_name}{q};")
                else:
                    statements.append(f"ALTER TABLE {tn} DROP INDEX {q}{idx_name}{q};")

            for fk in td.added_foreign_keys:
                statements.append(
                    f"ALTER TABLE {tn} ADD CONSTRAINT {q}{fk.name}{q} "
                    f"FOREIGN KEY ({q}{fk.column}{q}) REFERENCES "
                    f"{q}{fk.ref_table}{q} ({q}{fk.ref_column}{q}) "
                    f"ON DELETE {fk.on_delete} ON UPDATE {fk.on_update};"
                )
            for fk_name in td.removed_foreign_keys:
                if is_pg:
                    statements.append(
                        f"ALTER TABLE {tn} DROP CONSTRAINT {q}{fk_name}{q};"
                    )
                else:
                    statements.append(
                        f"ALTER TABLE {tn} DROP FOREIGN KEY {q}{fk_name}{q};"
                    )

        return statements


# Module-level singleton
sync_engine = SyncEngine()
