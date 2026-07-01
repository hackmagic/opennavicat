import { invoke } from "@tauri-apps/api/core";

export interface SshConfig {
  enabled: boolean;
  host: string;
  port: number;
  user: string;
  password: string;
}

export interface ConnectionInfo {
  name: string;
  host: string;
  port: number;
  user: string;
  password: string;
  database: string;
  engine: string;
  ssh?: SshConfig;
}

export interface QueryResult {
  columns: string[];
  rows: (string | number | boolean | null)[][];
  rows_affected: number;
  error: string | null;
  execution_time_ms: number;
}

export interface DatabaseInfo {
  name: string;
}

export interface TableInfo {
  name: string;
  table_type: string;
}

export interface ColumnInfo {
  name: string;
  data_type: string;
  nullable: boolean;
  is_primary_key: boolean;
  default_value: string | null;
  extra: string;
}

export interface IndexInfo {
  name: string;
  columns: string[];
  unique: boolean;
  index_type: string;
}

export interface ForeignKeyInfo {
  name: string;
  column: string;
  ref_table: string;
  ref_column: string;
  on_delete: string;
  on_update: string;
}

export async function listIndexes(
  connectionId: string,
  database: string,
  table: string,
): Promise<IndexInfo[]> {
  return invoke("list_indexes", { connectionId, database, table });
}

export async function listForeignKeys(
  connectionId: string,
  database: string,
  table: string,
): Promise<ForeignKeyInfo[]> {
  return invoke("list_foreign_keys", { connectionId, database, table });
}

export async function connect(info: ConnectionInfo): Promise<string> {
  return invoke("connect", { info });
}

export async function disconnect(id: string): Promise<void> {
  return invoke("disconnect", { id });
}

export async function executeQuery(
  connectionId: string,
  sql: string,
): Promise<QueryResult> {
  return invoke("execute_query", { connectionId, sql });
}

export async function listDatabases(
  connectionId: string,
): Promise<DatabaseInfo[]> {
  return invoke("list_databases", { connectionId });
}

export async function listTables(
  connectionId: string,
  database: string,
): Promise<TableInfo[]> {
  return invoke("list_tables", { connectionId, database });
}

export async function listColumns(
  connectionId: string,
  database: string,
  table: string,
): Promise<ColumnInfo[]> {
  return invoke("list_columns", { connectionId, database, table });
}

export interface SavedConnection {
  name: string;
  host: string;
  port: number;
  user: string;
  password: string;
  database: string;
  engine: string;
  ssh?: SshConfig;
}

export async function saveConnection(conn: SavedConnection): Promise<void> {
  return invoke("save_connection", { conn });
}

export async function loadConnections(): Promise<SavedConnection[]> {
  return invoke("load_connections");
}

export async function deleteConnection(name: string): Promise<void> {
  return invoke("delete_connection", { name });
}

export async function updateCell(
  connectionId: string,
  database: string,
  table: string,
  column: string,
  value: string | null,
  pkColumn: string,
  pkValue: string,
): Promise<number> {
  return invoke("update_cell", {
    connectionId,
    database,
    table,
    column,
    value,
    pkColumn,
    pkValue,
  });
}

export async function getTableDdl(
  connectionId: string,
  database: string,
  table: string,
): Promise<string> {
  return invoke("get_table_ddl", { connectionId, database, table });
}

export async function backupDatabase(
  connectionId: string,
  outputPath: string,
  includeRoutines: boolean,
): Promise<string> {
  return invoke("backup_database", { connectionId, outputPath, includeRoutines });
}

export async function restoreDatabase(
  connectionId: string,
  inputPath: string,
): Promise<string> {
  return invoke("restore_database", { connectionId, inputPath });
}

export interface SchemaDiffItem {
  table_name: string;
  diff_type: string;
  detail: string;
}

export interface UserInfo {
  user: string;
  host: string;
  plugin: string;
}

export async function listUsers(connectionId: string): Promise<UserInfo[]> {
  return invoke("list_users", { connectionId });
}

export async function createUser(connectionId: string, username: string, host: string, password: string): Promise<void> {
  return invoke("create_user", { connectionId, username, host, password });
}

export async function dropUser(connectionId: string, username: string, host: string): Promise<void> {
  return invoke("drop_user", { connectionId, username, host });
}

export interface DataSyncDiff {
  dml_type: string;
  sql: string;
  pk_value: string;
}

export async function dataSync(
  sourceConnId: string, sourceDb: string, sourceTable: string,
  targetConnId: string, targetDb: string, targetTable: string,
  pkColumn: string,
): Promise<DataSyncDiff[]> {
  return invoke("data_sync", { sourceConnId, sourceDb, sourceTable, targetConnId, targetDb, targetTable, pkColumn });
}

export async function schemaDiff(
  sourceConnId: string,
  sourceDb: string,
  targetConnId: string,
  targetDb: string,
): Promise<SchemaDiffItem[]> {
  return invoke("schema_diff", { sourceConnId, sourceDb, targetConnId, targetDb });
}
