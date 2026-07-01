use serde::{Deserialize, Serialize};
use sqlx::any::{AnyPoolOptions, AnyRow};
use sqlx::{AnyPool, Column, Row};
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SshConfig {
    pub enabled: bool,
    pub host: String,
    pub port: u16,
    pub user: String,
    pub password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectionInfo {
    pub name: String,
    pub host: String,
    pub port: u16,
    pub user: String,
    pub password: String,
    pub database: String,
    pub engine: String,
    #[serde(default)]
    pub ssh: SshConfig,
}

impl ConnectionInfo {
    fn url(&self) -> String {
        let scheme = if self.engine == "postgresql" {
            "postgres"
        } else {
            "mysql"
        };
        format!(
            "{}://{}:{}@{}:{}/{}",
            scheme, self.user, self.password, self.host, self.port, self.database
        )
    }
}

// ── SSH Tunnel ──

fn pick_port() -> u16 {
    // try ports 13306..13406
    for port in 13306..13406 {
        if std::net::TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return port;
        }
    }
    13306
}

fn start_ssh_tunnel(info: &ConnectionInfo) -> Result<(std::process::Child, u16), String> {
    if !info.ssh.enabled {
        return Err("SSH 未启用".to_string());
    }
    let local_port = pick_port();
    let mut child = std::process::Command::new("ssh")
        .arg("-L")
        .arg(format!("{}:{}:{}", local_port, info.host, info.port))
        .arg("-o")
        .arg("StrictHostKeyChecking=no")
        .arg("-o")
        .arg("UserKnownHostsFile=/dev/null")
        .arg("-N")
        .arg(format!("{}@{}", info.ssh.user, info.ssh.host))
        .arg("-p")
        .arg(info.ssh.port.to_string())
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| format!("启动 SSH 隧道失败: {}", e))?;
    // wait a moment for the tunnel to establish
    std::thread::sleep(Duration::from_millis(800));
    // quick check it's still alive
    match child.try_wait() {
        Ok(Some(status)) => return Err(format!("SSH 隧道已退出 (code: {:?})", status.code())),
        _ => {}
    }
    Ok((child, local_port))
}

#[derive(Debug, Clone, Serialize)]
pub struct QueryResult {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<serde_json::Value>>,
    pub rows_affected: u64,
    pub error: Option<String>,
    pub execution_time_ms: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct DatabaseInfo {
    pub name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct TableInfo {
    pub name: String,
    pub table_type: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ColumnInfo {
    pub name: String,
    pub data_type: String,
    pub nullable: bool,
    pub is_primary_key: bool,
    pub default_value: Option<String>,
    pub extra: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ForeignKeyInfo {
    pub name: String,
    pub column: String,
    pub ref_table: String,
    pub ref_column: String,
    pub on_delete: String,
    pub on_update: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IndexInfo {
    pub name: String,
    pub columns: Vec<String>,
    pub unique: bool,
    pub index_type: String,
}

pub struct AppState {
    pub pools: Mutex<HashMap<String, AnyPool>>,
    pub infos: Mutex<HashMap<String, ConnectionInfo>>,
    pub tunnels: Mutex<HashMap<String, (std::process::Child, u16)>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            pools: Mutex::new(HashMap::new()),
            infos: Mutex::new(HashMap::new()),
            tunnels: Mutex::new(HashMap::new()),
        }
    }
}

#[tauri::command]
pub async fn connect(state: tauri::State<'_, AppState>, info: ConnectionInfo) -> Result<String, String> {
    let id = Uuid::new_v4().to_string();
    let mut conn_info = info.clone();

    if info.ssh.enabled {
        let (child, local_port) = tokio::task::spawn_blocking(move || start_ssh_tunnel(&info))
            .await
            .map_err(|e| format!("SSH 隧道任务失败: {}", e))?
            .map_err(|e| format!("SSH 隧道失败: {}", e))?;
        conn_info.host = "127.0.0.1".to_string();
        conn_info.port = local_port;
        state.tunnels.lock().unwrap().insert(id.clone(), (child, local_port));
    }

    let pool = AnyPoolOptions::new()
        .max_connections(5)
        .connect(&conn_info.url())
        .await
        .map_err(|e| {
            // cleanup tunnel if connection fails
            if let Some((mut child, _)) = state.tunnels.lock().unwrap().remove(&id) {
                let _ = child.kill();
            }
            format!("连接失败: {}", e)
        })?;

    state.pools.lock().unwrap().insert(id.clone(), pool);
    state.infos.lock().unwrap().insert(id.clone(), conn_info);
    Ok(id)
}

#[tauri::command]
pub async fn disconnect(state: tauri::State<'_, AppState>, id: String) -> Result<(), String> {
    state.pools.lock().unwrap().remove(&id);
    state.infos.lock().unwrap().remove(&id);
    if let Some((mut child, _)) = state.tunnels.lock().unwrap().remove(&id) {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(())
}

#[tauri::command]
pub async fn execute_query(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    sql: String,
) -> Result<QueryResult, String> {
    let start = std::time::Instant::now();
    let pool = state
        .pools
        .lock()
        .unwrap()
        .get(&connection_id)
        .ok_or("连接已断开")?
        .clone();
    drop(state);

    let trimmed = sql.trim();
    let is_query = trimmed.to_uppercase().starts_with("SELECT")
        || trimmed.to_uppercase().starts_with("SHOW")
        || trimmed.to_uppercase().starts_with("DESCRIBE")
        || trimmed.to_uppercase().starts_with("EXPLAIN")
        || trimmed.to_uppercase().starts_with("WITH");

    if is_query {
        match sqlx::query(&sql).fetch_all(&pool).await {
            Ok(rows) => {
                let columns: Vec<String> = rows
                    .first()
                    .map(|r| r.columns().iter().map(|c| c.name().to_string()).collect())
                    .unwrap_or_default();
                let rows_data: Vec<Vec<serde_json::Value>> = rows
                    .iter()
                    .map(|r| {
                        r.columns()
                            .iter()
                            .map(|c| {
                                let idx = c.ordinal();
                                // ponytail: try_get<sqlx::types::Json> fails on Any, decode as string
                                let val = r
                                    .try_get::<String, _>(idx)
                                    .map(serde_json::Value::String)
                                    .or_else(|_| r.try_get::<i64, _>(idx).map(|v| serde_json::json!(v)))
                                    .or_else(|_| r.try_get::<f64, _>(idx).map(|v| serde_json::json!(v)))
                                    .or_else(|_| r.try_get::<bool, _>(idx).map(serde_json::Value::Bool))
                                    .unwrap_or(serde_json::Value::Null);
                                val
                            })
                            .collect()
                    })
                    .collect();
                Ok(QueryResult {
                    columns,
                    rows: rows_data,
                    rows_affected: rows.len() as u64,
                    error: None,
                    execution_time_ms: start.elapsed().as_millis() as u64,
                })
            }
            Err(e) => Ok(QueryResult {
                columns: vec![],
                rows: vec![],
                rows_affected: 0,
                error: Some(e.to_string()),
                execution_time_ms: start.elapsed().as_millis() as u64,
            }),
        }
    } else {
        match sqlx::query(&sql).execute(&pool).await {
            Ok(result) => Ok(QueryResult {
                columns: vec![],
                rows: vec![],
                rows_affected: result.rows_affected(),
                error: None,
                execution_time_ms: start.elapsed().as_millis() as u64,
            }),
            Err(e) => Ok(QueryResult {
                columns: vec![],
                rows: vec![],
                rows_affected: 0,
                error: Some(e.to_string()),
                execution_time_ms: start.elapsed().as_millis() as u64,
            }),
        }
    }
}

#[tauri::command]
pub async fn list_databases(
    state: tauri::State<'_, AppState>,
    connection_id: String,
) -> Result<Vec<DatabaseInfo>, String> {
    let pool = state
        .pools
        .lock()
        .unwrap()
        .get(&connection_id)
        .ok_or("连接已断开")?
        .clone();

    let info = state.infos.lock().unwrap().get(&connection_id).cloned();
    let sql = match info.map(|i| i.engine).as_deref() {
        Some("postgresql") => "SELECT datname AS name FROM pg_database WHERE datistemplate = false ORDER BY datname",
        _ => "SELECT SCHEMA_NAME AS name FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME",
    };

    let rows = sqlx::query(sql)
        .fetch_all(&pool)
        .await
        .map_err(|e| e.to_string())?;

    Ok(rows
        .iter()
        .map(|r| DatabaseInfo {
            name: r.get::<String, _>("name"),
        })
        .collect())
}

#[tauri::command]
pub async fn list_tables(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    database: String,
) -> Result<Vec<TableInfo>, String> {
    let pool = state
        .pools
        .lock()
        .unwrap()
        .get(&connection_id)
        .ok_or("连接已断开")?
        .clone();

    let info = state.infos.lock().unwrap().get(&connection_id).cloned();
    let engine = info.as_ref().map(|i| i.engine.as_str()).unwrap_or("");
    let (sql, db) = match engine {
        "postgresql" => (
            "SELECT tablename AS name, 'TABLE' AS table_type FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename",
            database,
        ),
        _ => (
            "SELECT TABLE_NAME AS name, TABLE_TYPE AS table_type FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? ORDER BY TABLE_NAME",
            database,
        ),
    };

    let rows = if engine == "postgresql" {
        sqlx::query(sql)
            .fetch_all(&pool)
            .await
            .map_err(|e| e.to_string())?
    } else {
        sqlx::query(sql)
            .bind(&db)
            .fetch_all(&pool)
            .await
            .map_err(|e| e.to_string())?
    };

    Ok(rows
        .iter()
        .map(|r| TableInfo {
            name: r.get::<String, _>("name"),
            table_type: r
                .try_get::<String, _>("table_type")
                .unwrap_or_default(),
        })
        .collect())
}

#[tauri::command]
pub async fn list_columns(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    database: String,
    table: String,
) -> Result<Vec<ColumnInfo>, String> {
    let pool = state
        .pools
        .lock()
        .unwrap()
        .get(&connection_id)
        .ok_or("连接已断开")?
        .clone();

    let info = state.infos.lock().unwrap().get(&connection_id).cloned();
    let engine = info.as_ref().map(|i| i.engine.as_str()).unwrap_or("").to_string();

    if engine == "postgresql" {
        let sql = r#"
            SELECT
                a.attname AS name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                NOT a.attnotnull AS nullable,
                COALESCE(i.indisprimary, false) AS is_primary_key,
                pg_catalog.pg_get_expr(d.adbin, d.adrelid) AS default_value
            FROM pg_catalog.pg_attribute a
            LEFT JOIN pg_catalog.pg_index i ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) AND i.indisprimary
            LEFT JOIN pg_catalog.pg_attrdef d ON a.attrelid = d.adrelid AND a.attnum = d.adnum
            WHERE a.attrelid = ($1 || '.' || $2)::regclass
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        "#;
        let rows = sqlx::query(sql)
            .bind(&database)
            .bind(&table)
            .fetch_all(&pool)
            .await
            .map_err(|e| e.to_string())?;

        Ok(rows
            .iter()
            .map(|r| ColumnInfo {
                name: r.get("name"),
                data_type: r.get("data_type"),
                nullable: r.get("nullable"),
                is_primary_key: r.get("is_primary_key"),
                default_value: r.try_get("default_value").ok(),
                extra: String::new(),
            })
            .collect())
    } else {
        let sql = r#"
            SELECT
                COLUMN_NAME AS name, DATA_TYPE AS data_type,
                IS_NULLABLE = 'YES' AS nullable,
                COLUMN_KEY = 'PRI' AS is_primary_key,
                COLUMN_DEFAULT AS default_value,
                EXTRA AS extra
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        "#;
        let rows = sqlx::query(sql)
            .bind(&database)
            .bind(&table)
            .fetch_all(&pool)
            .await
            .map_err(|e| e.to_string())?;

        Ok(rows
            .iter()
            .map(|r| ColumnInfo {
                name: r.get("name"),
                data_type: r.try_get::<String, _>("data_type").unwrap_or_else(|_| String::from_utf8(r.get::<Vec<u8>, _>("data_type")).unwrap_or_default()),
                nullable: r.get("nullable"),
                is_primary_key: r.get("is_primary_key"),
                default_value: r.try_get::<String, _>("default_value").ok().or_else(|| r.try_get::<Vec<u8>, _>("default_value").ok().map(|b| String::from_utf8(b).unwrap_or_default())),
                extra: r.try_get::<String, _>("extra").unwrap_or_else(|_| r.try_get::<Vec<u8>, _>("extra").map(|b| String::from_utf8(b).unwrap_or_default()).unwrap_or_default()),
            })
            .collect())
    }
}

#[tauri::command]
pub async fn list_indexes(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    _database: String,
    table: String,
) -> Result<Vec<IndexInfo>, String> {
    let pool = state.pools.lock().unwrap().get(&connection_id).ok_or("连接已断开")?.clone();
    let info = state.infos.lock().unwrap().get(&connection_id).cloned();
    let engine = info.as_ref().map(|i| i.engine.as_str()).unwrap_or("").to_string();

    if engine == "postgresql" {
        let rows = sqlx::query(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = $1 ORDER BY indexname"
        )
            .bind(&table)
            .fetch_all(&pool)
            .await
            .map_err(|e| e.to_string())?;

        Ok(rows.iter().map(|r| {
            let cols = extract_pg_index_columns(r.try_get::<String,_>("indexdef").unwrap_or_default());
            IndexInfo {
                name: r.try_get("indexname").unwrap_or_default(),
                columns: cols,
                unique: r.try_get::<String,_>("indexdef").unwrap_or_default().contains("UNIQUE"),
                index_type: "BTREE".into(),
            }
        }).collect())
    } else {
        let sql = format!("SHOW INDEX FROM `{}`", table.replace('`', "``"));
        let rows = sqlx::query(&sql)
            .fetch_all(&pool)
            .await
            .map_err(|e| e.to_string())?;
        // group by Key_name
            let mut map: std::collections::BTreeMap<String, (Vec<String>, bool, String)> = std::collections::BTreeMap::new();
        for r in &rows {
            let name: String = r.get("Key_name");
            let col: String = r.get("Column_name");
            let non_unique: i32 = r.get("Non_unique");
            let idx_type: String = r.get("Index_type");
            let entry = map.entry(name.clone()).or_insert((vec![], non_unique == 0, idx_type.clone()));
            entry.0.push(col);
            entry.1 = non_unique == 0;
            entry.2 = idx_type;
        }
        Ok(map.into_iter().map(|(name, (columns, unique, index_type))| IndexInfo { name, columns, unique, index_type }).collect())
    }
}

#[tauri::command]
pub async fn list_foreign_keys(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    database: String,
    table: String,
) -> Result<Vec<ForeignKeyInfo>, String> {
    let pool;
    let info;
    {
        let p = state.pools.lock().unwrap();
        pool = p.get(&connection_id).ok_or("连接已断开")?.clone();
    }
    {
        let i = state.infos.lock().unwrap();
        info = i.get(&connection_id).cloned();
    }
    let engine = info.as_ref().map(|i| i.engine.as_str()).unwrap_or("").to_string();

    if engine == "postgresql" {
        let rows = sqlx::query(r#"
            SELECT
                tc.constraint_name AS name,
                kcu.column_name AS column_name,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column,
                rc.update_rule AS on_update,
                rc.delete_rule AS on_delete
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
            JOIN information_schema.referential_constraints rc ON tc.constraint_name = rc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = $1
        "#).bind(&table).fetch_all(&pool).await.map_err(|e| e.to_string())?;
        Ok(rows.iter().map(|r| ForeignKeyInfo {
            name: r.try_get("name").unwrap_or_default(),
            column: r.try_get("column_name").unwrap_or_default(),
            ref_table: r.try_get("ref_table").unwrap_or_default(),
            ref_column: r.try_get("ref_column").unwrap_or_default(),
            on_delete: r.try_get("on_delete").unwrap_or_default(),
            on_update: r.try_get("on_update").unwrap_or_default(),
        }).collect())
    } else {
        let rows = sqlx::query(
            "SELECT CONSTRAINT_NAME AS name, COLUMN_NAME AS column_name, REFERENCED_TABLE_NAME AS ref_table, REFERENCED_COLUMN_NAME AS ref_column FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND REFERENCED_TABLE_NAME IS NOT NULL"
        ).bind(&database).bind(&table).fetch_all(&pool).await.map_err(|e| e.to_string())?;
        Ok(rows.iter().map(|r| ForeignKeyInfo {
            name: r.try_get("name").unwrap_or_default(),
            column: r.try_get("column_name").unwrap_or_default(),
            ref_table: r.try_get("ref_table").unwrap_or_default(),
            ref_column: r.try_get("ref_column").unwrap_or_default(),
            on_delete: String::new(),
            on_update: String::new(),
        }).collect())
    }
}

fn extract_pg_index_columns(def: String) -> Vec<String> {
    // indexdef looks like: "CREATE UNIQUE INDEX idx_name ON public.tablename USING btree (col1, col2)"
    if let Some(start) = def.find('(') {
        if let Some(end) = def.rfind(')') {
            return def[start+1..end].split(',').map(|s| s.trim().trim_matches('"').to_string()).collect();
        }
    }
    vec![]
}

// ── Connection persistence ──

fn connections_path() -> Result<std::path::PathBuf, String> {
    let mut path = dirs::config_dir().ok_or("无法获取配置目录")?;
    path.push("OpenNavicat");
    std::fs::create_dir_all(&path).map_err(|e| format!("创建配置目录失败: {}", e))?;
    path.push("connections.json");
    Ok(path)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SavedConnection {
    pub name: String,
    pub host: String,
    pub port: u16,
    pub user: String,
    pub password: String,
    pub database: String,
    pub engine: String,
}

#[tauri::command]
pub async fn save_connection(conn: SavedConnection) -> Result<(), String> {
    let path = connections_path()?;
    let mut list: Vec<SavedConnection> = if path.exists() {
        let data = std::fs::read_to_string(&path).map_err(|e| format!("读取连接文件失败: {}", e))?;
        serde_json::from_str(&data).unwrap_or_default()
    } else {
        vec![]
    };
    if let Some(pos) = list.iter().position(|c| c.name == conn.name) {
        list[pos] = conn;
    } else {
        list.push(conn);
    }
    let data = serde_json::to_string_pretty(&list).map_err(|e| format!("序列化失败: {}", e))?;
    std::fs::write(&path, data).map_err(|e| format!("写入连接文件失败: {}", e))?;
    Ok(())
}

#[tauri::command]
pub async fn load_connections() -> Result<Vec<SavedConnection>, String> {
    let path = connections_path()?;
    if !path.exists() {
        return Ok(vec![]);
    }
    let data = std::fs::read_to_string(&path).map_err(|e| format!("读取连接文件失败: {}", e))?;
    serde_json::from_str(&data).map_err(|e| format!("解析连接文件失败: {}", e))
}

#[tauri::command]
pub async fn get_table_ddl(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    database: String,
    table: String,
) -> Result<String, String> {
    let pool = state
        .pools
        .lock()
        .unwrap()
        .get(&connection_id)
        .ok_or("连接已断开")?
        .clone();
    let info = state.infos.lock().unwrap().get(&connection_id).cloned();
    let engine = info.as_ref().map(|i| i.engine.as_str()).unwrap_or("");

    if engine == "postgresql" {
        let row = sqlx::query(
            "SELECT pg_catalog.pg_get_ddl($1::regclass) AS ddl"
        )
            .bind(format!("{}.{}", database, table))
            .fetch_one(&pool)
            .await
            .map_err(|e| e.to_string())?;
        Ok(row.get::<String, _>("ddl"))
    } else {
        let sql = format!("SHOW CREATE TABLE `{}`.`{}`", database, table);
        let row = sqlx::query(&sql)
            .fetch_one(&pool)
            .await
            .map_err(|e| e.to_string())?;
        let ddl: String = row.try_get("Create Table").unwrap_or_default();
        Ok(ddl)
    }
}

#[tauri::command]
pub async fn update_cell(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    database: String,
    table: String,
    column: String,
    value: Option<String>,
    pk_column: String,
    pk_value: String,
) -> Result<u64, String> {
    let pool = state
        .pools
        .lock()
        .unwrap()
        .get(&connection_id)
        .ok_or("连接已断开")?
        .clone();
    let info = state.infos.lock().unwrap().get(&connection_id).cloned();
    let engine = info.as_ref().map(|i| i.engine.as_str()).unwrap_or("");
    let (qtable, qcol, qpk) = if engine == "postgresql" {
        (format!("\"{}\"", table), format!("\"{}\"", column), format!("\"{}\"", pk_column))
    } else {
        (format!("`{}`", table), format!("`{}`", column), format!("`{}`", pk_column))
    };
    let sql = format!("UPDATE {}.{} SET {} = ? WHERE {} = ?", quote_id(&database, engine), qtable, qcol, qpk);
    let result = if let Some(v) = value {
        sqlx::query(&sql)
            .bind(&v)
            .bind(&pk_value)
            .execute(&pool)
            .await
            .map_err(|e| format!("更新失败: {}", e))?
    } else {
        sqlx::query(&sql)
            .bind(Option::<String>::None)
            .bind(&pk_value)
            .execute(&pool)
            .await
            .map_err(|e| format!("更新失败: {}", e))?
    };
    Ok(result.rows_affected())
}

fn get_host_port(state: &AppState, connection_id: &str, info: &ConnectionInfo) -> (String, u16) {
    let tunnels = state.tunnels.lock().unwrap();
    if let Some((_, port)) = tunnels.get(connection_id) {
        ("127.0.0.1".into(), *port)
    } else {
        (info.host.clone(), info.port)
    }
}

#[tauri::command]
pub async fn backup_database(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    output_path: String,
    include_routines: bool,
) -> Result<String, String> {
    let info = state.infos.lock().unwrap().get(&connection_id).cloned().ok_or("连接未找到")?;
    let (host, port) = get_host_port(&state, &connection_id, &info);
    let use_tunnel = state.tunnels.lock().unwrap().contains_key(&connection_id);

    let result = if info.engine == "postgresql" {
        std::process::Command::new("pg_dump")
            .args(["--host", &host, "--port", &port.to_string(), "--username", &info.user])
            .env("PGPASSWORD", &info.password)
            .arg(&info.database)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .output()
            .map_err(|e| format!("pg_dump 执行失败 (请确认已安装并加入 PATH): {}", e))?
    } else {
        let mut cmd = std::process::Command::new("mysqldump");
        cmd.args(["--host", &host, "--port", &port.to_string(), "--user", &info.user]);
        cmd.args([&format!("--password={}", &info.password)]);
        cmd.arg("--single-transaction");
        cmd.arg("--skip-lock-tables");
        if include_routines {
            cmd.arg("--routines").arg("--triggers").arg("--events");
        }
        // If using SSH tunnel, we may want to suppress SSL errors
        if use_tunnel {
            cmd.arg("--ssl-mode=DISABLED");
        }
        cmd.arg(&info.database);
        cmd.stdout(std::process::Stdio::piped());
        cmd.stderr(std::process::Stdio::piped());
        cmd.output().map_err(|e| format!("mysqldump 执行失败 (请确认已安装并加入 PATH): {}", e))?
    };

    if !result.status.success() {
        let stderr = String::from_utf8_lossy(&result.stderr);
        return Err(format!("备份失败: {}", stderr));
    }

    let final_path = if output_path.ends_with(".sql") { output_path.clone() } else { format!("{}.sql", output_path) };
    std::fs::write(&final_path, &result.stdout).map_err(|e| format!("写入文件失败: {}", e))?;
    Ok(final_path)
}

#[tauri::command]
pub async fn restore_database(
    state: tauri::State<'_, AppState>,
    connection_id: String,
    input_path: String,
) -> Result<String, String> {
    let info = state.infos.lock().unwrap().get(&connection_id).cloned().ok_or("连接未找到")?;
    let (host, port) = get_host_port(&state, &connection_id, &info);

    if !std::path::Path::new(&input_path).exists() {
        return Err("文件不存在".into());
    }

    if info.engine == "postgresql" {
        let child = std::process::Command::new("psql")
            .args(["--host", &host, "--port", &port.to_string(), "--username", &info.user])
            .env("PGPASSWORD", &info.password)
            .arg("-d").arg(&info.database)
            .arg("-f").arg(&input_path)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("psql 执行失败: {}", e))?;
        let output = child.wait_with_output().map_err(|e| format!("等待 psql 完成失败: {}", e))?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).into());
        }
        Ok(format!("恢复完成 ({} bytes)", input_path.len()))
    } else {
        let child = std::process::Command::new("mysql")
            .args(["--host", &host, "--port", &port.to_string(), "--user", &info.user])
            .args([&format!("--password={}", &info.password)])
            .arg(&info.database)
            .stdin(std::fs::File::open(&input_path).map_err(|e| format!("打开文件失败: {}", e))?)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("mysql 执行失败: {}", e))?;
        let output = child.wait_with_output().map_err(|e| format!("等待 mysql 完成失败: {}", e))?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).into());
        }
        Ok(format!("恢复完成 ({} bytes)", std::fs::metadata(&input_path).map(|m| m.len()).unwrap_or(0)))
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct UserInfo {
    pub user: String,
    pub host: String,
    pub plugin: String,
}

#[tauri::command]
pub async fn list_users(state: tauri::State<'_, AppState>, connection_id: String) -> Result<Vec<UserInfo>, String> {
    let pool = state.pools.lock().unwrap().get(&connection_id).ok_or("连接已断开")?.clone();
    drop(state);
    let rows = sqlx::query("SELECT User AS user, Host AS host, plugin AS plugin FROM mysql.user ORDER BY user")
        .fetch_all(&pool).await.map_err(|e| format!("获取用户列表失败: {}", e))?;
    Ok(rows.iter().map(|r| UserInfo {
        user: r.try_get("user").unwrap_or_default(),
        host: r.try_get("host").unwrap_or_default(),
        plugin: r.try_get("plugin").unwrap_or_default(),
    }).collect())
}

#[tauri::command]
pub async fn create_user(state: tauri::State<'_, AppState>, connection_id: String, username: String, host: String, password: String) -> Result<(), String> {
    let pool = state.pools.lock().unwrap().get(&connection_id).ok_or("连接已断开")?.clone();
    drop(state);
    let sql = format!("CREATE USER '{}'@'{}' IDENTIFIED BY '{}'", username.replace('\'', "\\'"), host.replace('\'', "\\'"), password.replace('\'', "\\'"));
    sqlx::query(&sql).execute(&pool).await.map_err(|e| format!("创建用户失败: {}", e))?;
    Ok(())
}

#[tauri::command]
pub async fn drop_user(state: tauri::State<'_, AppState>, connection_id: String, username: String, host: String) -> Result<(), String> {
    let pool = state.pools.lock().unwrap().get(&connection_id).ok_or("连接已断开")?.clone();
    drop(state);
    let sql = format!("DROP USER '{}'@'{}'", username.replace('\'', "\\'"), host.replace('\'', "\\'"));
    sqlx::query(&sql).execute(&pool).await.map_err(|e| format!("删除用户失败: {}", e))?;
    Ok(())
}

#[derive(Debug, Clone, Serialize)]
pub struct DataSyncDiff {
    pub dml_type: String,
    pub sql: String,
    pub pk_value: String,
}

#[tauri::command]
pub async fn data_sync(
    state: tauri::State<'_, AppState>,
    source_conn_id: String, source_db: String, source_table: String,
    target_conn_id: String, _target_db: String, target_table: String,
    pk_column: String,
) -> Result<Vec<DataSyncDiff>, String> {
    let (src_pool, tgt_pool): (AnyPool, AnyPool);
    {
        let p = state.pools.lock().unwrap();
        src_pool = p.get(&source_conn_id).ok_or("源连接已断开")?.clone();
        tgt_pool = p.get(&target_conn_id).ok_or("目标连接已断开")?.clone();
    }

    let pk = if pk_column.is_empty() {
        let engine;
        {
            let infos = state.infos.lock().unwrap();
            let src_info = infos.get(&source_conn_id).ok_or("源连接未找到")?.clone();
            engine = src_info.engine;
        }
        let cols: Vec<ColumnInfo> = if engine == "postgresql" {
            let rows = sqlx::query(r#"SELECT a.attname AS name FROM pg_catalog.pg_attribute a WHERE a.attrelid = ($1 || '.' || $2)::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"#)
                .bind(&source_db).bind(&source_table).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: String::new(), nullable: false, is_primary_key: false, default_value: None, extra: String::new() }).collect()
        } else {
            let rows = sqlx::query("SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION")
                .bind(&source_db).bind(&source_table).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: String::new(), nullable: false, is_primary_key: false, default_value: None, extra: String::new() }).collect()
        };
        cols.first().ok_or("无法检测主键，请手动指定")?.name.clone()
    } else {
        pk_column
    };

    fn qid(name: &str) -> String { format!("`{}`", name) }

    // Build column list
    let col_names: Vec<String> = {
        let cols: Vec<ColumnInfo> = {
            let rows = sqlx::query("SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION")
                .bind(&source_db).bind(&source_table).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: String::new(), nullable: false, is_primary_key: false, default_value: None, extra: String::new() }).collect()
        };
        cols.iter().map(|c| c.name.clone()).collect()
    };

    let col_list = col_names.iter().map(|c| qid(c)).collect::<Vec<_>>().join(", ");

    // Fetch all rows as string values
    let col_exprs = col_names.iter().map(|c| format!("CAST({} AS CHAR)", qid(c))).collect::<Vec<_>>().join(", ");
    let sql = format!("SELECT {} FROM {} ORDER BY {}", col_exprs, qid(&source_table), qid(&pk));
    let src_raw = sqlx::query(&sql).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
    let sql2 = format!("SELECT {} FROM {} ORDER BY {}", col_exprs, qid(&target_table), qid(&pk));
    let tgt_raw = sqlx::query(&sql2).fetch_all(&tgt_pool).await.map_err(|e| e.to_string())?;

    fn get_str(row: &AnyRow, i: usize) -> String {
        let v: Result<Option<String>, _> = row.try_get(i);
        v.ok().flatten().unwrap_or_default()
    }

    let src_rows: Vec<Vec<String>> = src_raw.iter().map(|r| (0..col_names.len()).map(|i| get_str(r, i)).collect()).collect();
    let tgt_rows: Vec<Vec<String>> = tgt_raw.iter().map(|r| (0..col_names.len()).map(|i| get_str(r, i)).collect()).collect();

    let pk_idx = col_names.iter().position(|c| c == &pk).unwrap_or(0);

    let src_map: std::collections::HashMap<String, Vec<String>> = src_rows.into_iter().map(|row| {
        let pkv = row[pk_idx].clone();
        (pkv, row)
    }).collect();

    let tgt_map: std::collections::HashMap<String, Vec<String>> = tgt_rows.into_iter().map(|row| {
        let pkv = row[pk_idx].clone();
        (pkv, row)
    }).collect();

    let mut diffs = Vec::new();

    for (pkv, row) in &src_map {
        if !tgt_map.contains_key(pkv) {
            let vals = row.iter().map(|v| if v.is_empty() { "NULL".into() } else { format!("'{}'", v.replace('\'', "''")) }).collect::<Vec<_>>().join(", ");
            diffs.push(DataSyncDiff { dml_type: "INSERT".into(), sql: format!("INSERT INTO {} ({}) VALUES ({});", qid(&target_table), col_list, vals), pk_value: pkv.clone() });
        }
    }

    for (pkv, _) in &tgt_map {
        if !src_map.contains_key(pkv) {
            diffs.push(DataSyncDiff { dml_type: "DELETE".into(), sql: format!("DELETE FROM {} WHERE {} = '{}';", qid(&target_table), qid(&pk), pkv.replace('\'', "''")), pk_value: pkv.clone() });
        }
    }

    for (pkv, src_row) in &src_map {
        if let Some(tgt_row) = tgt_map.get(pkv) {
            let mut sets = Vec::new();
            for i in 0..col_names.len() {
                if src_row[i] != tgt_row[i] {
                    let v = if src_row[i].is_empty() { "NULL".into() } else { format!("'{}'", src_row[i].replace('\'', "''")) };
                    sets.push(format!("{} = {}", qid(&col_names[i]), v));
                }
            }
            if !sets.is_empty() {
                diffs.push(DataSyncDiff { dml_type: "UPDATE".into(), sql: format!("UPDATE {} SET {} WHERE {} = '{}';", qid(&target_table), sets.join(", "), qid(&pk), pkv.replace('\'', "''")), pk_value: pkv.clone() });
            }
        }
    }

    Ok(diffs)
}

#[derive(Debug, Clone, Serialize)]
pub struct SchemaDiff {
    pub table_name: String,
    pub diff_type: String,
    pub detail: String,
}

#[tauri::command]
pub async fn schema_diff(
    state: tauri::State<'_, AppState>,
    source_conn_id: String,
    source_db: String,
    target_conn_id: String,
    target_db: String,
) -> Result<Vec<SchemaDiff>, String> {
    let (src_pool, tgt_pool): (AnyPool, AnyPool);
    let (src_info, tgt_info): (ConnectionInfo, ConnectionInfo);
    {
        let p = state.pools.lock().unwrap();
        src_pool = p.get(&source_conn_id).ok_or("源连接已断开")?.clone();
        tgt_pool = p.get(&target_conn_id).ok_or("目标连接已断开")?.clone();
    }
    {
        let i = state.infos.lock().unwrap();
        src_info = i.get(&source_conn_id).ok_or("源连接未找到")?.clone();
        tgt_info = i.get(&target_conn_id).ok_or("目标连接未找到")?.clone();
    }

    let src_engine = src_info.engine;
    let tgt_engine = tgt_info.engine;

    let src_tables: Vec<String> = if src_engine == "postgresql" {
        let rows = sqlx::query("SELECT tablename AS name FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
            .fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
        rows.iter().map(|r| r.try_get::<String, _>("name").unwrap_or_default()).collect()
    } else {
        let rows = sqlx::query("SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'")
            .bind(&source_db).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
        rows.iter().map(|r| r.try_get::<String, _>("name").unwrap_or_default()).collect()
    };

    let tgt_tables: Vec<String> = if tgt_engine == "postgresql" {
        let rows = sqlx::query("SELECT tablename AS name FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
            .fetch_all(&tgt_pool).await.map_err(|e| e.to_string())?;
        rows.iter().map(|r| r.try_get::<String, _>("name").unwrap_or_default()).collect()
    } else {
        let rows = sqlx::query("SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'")
            .bind(&target_db).fetch_all(&tgt_pool).await.map_err(|e| e.to_string())?;
        rows.iter().map(|r| r.try_get::<String, _>("name").unwrap_or_default()).collect()
    };

    let mut diffs: Vec<SchemaDiff> = Vec::new();

    // tables in source not in target
    for t in &src_tables {
        if !tgt_tables.contains(t) {
            diffs.push(SchemaDiff { table_name: t.clone(), diff_type: "ADD TABLE".into(), detail: "表仅存在于源库".into() });
        }
    }
    for t in &tgt_tables {
        if !src_tables.contains(t) {
            diffs.push(SchemaDiff { table_name: t.clone(), diff_type: "DROP TABLE".into(), detail: "表仅存在于目标库".into() });
        }
    }

    // column-level comparison for common tables
    for t in &src_tables {
        if !tgt_tables.contains(t) { continue; }
        let src_cols: Vec<ColumnInfo> = if src_engine == "postgresql" {
            let rows = sqlx::query(r#"SELECT a.attname AS name, pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type, NOT a.attnotnull AS nullable FROM pg_catalog.pg_attribute a WHERE a.attrelid = ($1 || '.' || $2)::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"#)
                .bind(&source_db).bind(t).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: r.get("data_type"), nullable: r.get("nullable"), is_primary_key: false, default_value: None, extra: String::new() }).collect()
        } else {
            let rows = sqlx::query("SELECT COLUMN_NAME AS name, DATA_TYPE AS data_type, IS_NULLABLE = 'YES' AS nullable, EXTRA AS extra FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION")
                .bind(&source_db).bind(t).fetch_all(&src_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: r.get("data_type"), nullable: r.get("nullable"), is_primary_key: false, default_value: None, extra: r.try_get("extra").unwrap_or_default() }).collect()
        };

        let tgt_cols: Vec<ColumnInfo> = if tgt_engine == "postgresql" {
            let rows = sqlx::query(r#"SELECT a.attname AS name, pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type, NOT a.attnotnull AS nullable FROM pg_catalog.pg_attribute a WHERE a.attrelid = ($1 || '.' || $2)::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"#)
                .bind(&target_db).bind(t).fetch_all(&tgt_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: r.get("data_type"), nullable: r.get("nullable"), is_primary_key: false, default_value: None, extra: String::new() }).collect()
        } else {
            let rows = sqlx::query("SELECT COLUMN_NAME AS name, DATA_TYPE AS data_type, IS_NULLABLE = 'YES' AS nullable, EXTRA AS extra FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION")
                .bind(&target_db).bind(t).fetch_all(&tgt_pool).await.map_err(|e| e.to_string())?;
            rows.iter().map(|r| ColumnInfo { name: r.get("name"), data_type: r.get("data_type"), nullable: r.get("nullable"), is_primary_key: false, default_value: None, extra: r.try_get("extra").unwrap_or_default() }).collect()
        };

        for c in &src_cols {
            if !tgt_cols.iter().any(|tc| tc.name == c.name) {
                diffs.push(SchemaDiff { table_name: t.clone(), diff_type: "ADD COLUMN".into(), detail: format!("列 {} {} {}", c.name, c.data_type, if c.nullable { "NULL" } else { "NOT NULL" }) });
            }
        }
        for c in &tgt_cols {
            if !src_cols.iter().any(|sc| sc.name == c.name) {
                diffs.push(SchemaDiff { table_name: t.clone(), diff_type: "DROP COLUMN".into(), detail: format!("列 {}", c.name) });
            }
        }
    }

    Ok(diffs)
}

fn quote_id(name: &str, engine: &str) -> String {
    if engine == "postgresql" {
        format!("\"{}\"", name)
    } else {
        format!("`{}`", name)
    }
}

#[tauri::command]
pub async fn delete_connection(name: String) -> Result<(), String> {
    let path = connections_path()?;
    if !path.exists() {
        return Ok(());
    }
    let data = std::fs::read_to_string(&path).map_err(|e| format!("读取连接文件失败: {}", e))?;
    let mut list: Vec<SavedConnection> = serde_json::from_str(&data).unwrap_or_default();
    list.retain(|c| c.name != name);
    let data = serde_json::to_string_pretty(&list).map_err(|e| format!("序列化失败: {}", e))?;
    std::fs::write(&path, data).map_err(|e| format!("写入连接文件失败: {}", e))?;
    Ok(())
}
