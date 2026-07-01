mod db;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    sqlx::any::install_default_drivers();
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(db::AppState::new())
        .invoke_handler(tauri::generate_handler![
            db::connect,
            db::disconnect,
            db::execute_query,
            db::list_databases,
            db::list_tables,
            db::list_columns,
            db::save_connection,
            db::load_connections,
            db::delete_connection,
            db::get_table_ddl,
            db::update_cell,
            db::list_indexes,
            db::backup_database,
            db::restore_database,
            db::schema_diff,
            db::list_users,
            db::create_user,
            db::drop_user,
            db::data_sync,
            db::list_foreign_keys,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
