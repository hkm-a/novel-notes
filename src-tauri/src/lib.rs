mod chapters;
mod commands;
mod llm;
mod storage;

use std::sync::{Arc, Mutex};

use commands::AppState;
use storage::Storage;
use tauri::{Emitter, Manager};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let data_dir = app
                .path()
                .app_data_dir()
                .map_err(|e| std::io::Error::other(e.to_string()))?;
            let storage = Arc::new(
                Storage::open(&data_dir.join("library.db"))
                    .map_err(|e| std::io::Error::other(e))?,
            );
            app.manage(AppState {
                storage,
                jobs: Arc::new(Mutex::new(Default::default())),
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::DragDrop(tauri::DragDropEvent::Drop { paths, .. }) = event {
                let paths: Vec<String> = paths
                    .iter()
                    .map(|p| p.to_string_lossy().into_owned())
                    .collect();
                let _ = window.emit("app://drag-drop", serde_json::json!({ "paths": paths }));
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_books,
            commands::get_book,
            commands::import_path,
            commands::delete_book,
            commands::update_book,
            commands::generate_chapter,
            commands::generate_all,
            commands::list_jobs,
            commands::get_settings,
            commands::save_settings,
            commands::pick_file,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
