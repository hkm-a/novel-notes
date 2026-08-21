use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::State;
use uuid::Uuid;

use crate::chapters;
use crate::llm;
use crate::storage::{BookDetail, BookSummary, ChapterRow, Settings, Storage};

#[derive(Debug, Clone, Serialize)]
pub struct Job {
    pub id: String,
    pub book_id: String,
    pub chapter_id: String,
    pub chapter_title: String,
    pub status: String,
    pub progress: u8,
    pub error: Option<String>,
}

pub struct AppState {
    pub storage: Arc<Storage>,
    pub jobs: Arc<Mutex<HashMap<String, Job>>>,
}

impl AppState {
    fn submit_job(&self, book_id: String, chapter_row: ChapterRow) -> Result<Job, String> {
        let mut jobs = self.jobs.lock().map_err(|e| e.to_string())?;
        // 已存在进行中的任务则直接返回
        for job in jobs.values() {
            if job.chapter_id == chapter_row.id && (job.status == "queued" || job.status == "running") {
                return Ok(job.clone());
            }
        }

        let id = Uuid::new_v4().simple().to_string()[..12].to_string();
        jobs.insert(
            id.clone(),
            Job {
                id: id.clone(),
                book_id: book_id.clone(),
                chapter_id: chapter_row.id.clone(),
                chapter_title: chapter_row.title.clone(),
                status: "queued".into(),
                progress: 0,
                error: None,
            },
        );
        drop(jobs);

        let storage = self.storage.clone();
        let jobs_state = self.jobs.clone();
        let settings = storage.get_settings().unwrap_or_default();
        let chapter = chapter_row.clone();
        let thread_id = id.clone();

        std::thread::spawn(move || {
            update_job(&jobs_state, &thread_id, "running", 10, None);
            // 取前面最多 5 个已完成章节的笔记作为前情提要，保持剧情连贯。
            let context = if let Ok(book) = storage.get_book(&book_id) {
                book.chapters
                    .iter()
                    .filter(|c| c.idx < chapter.idx && c.status == "done" && c.note.is_some())
                    .rev()
                    .take(5)
                    .collect::<Vec<_>>()
                    .iter()
                    .rev()
                    .map(|c| {
                        format!("【{}】\n{}", c.title, c.note.clone().unwrap_or_default())
                    })
                    .collect::<Vec<_>>()
            } else {
                Vec::new()
            };
            let result = llm::generate_chapter_note(
                &settings,
                &chapter.title,
                &chapter.text,
                &context,
            );
            match result {
                Ok(note) => {
                    let _ = storage.update_chapter_note(&chapter.id, Some(&note), "done", None);
                    update_job(&jobs_state, &thread_id, "done", 100, None);
                }
                Err(err) => {
                    let _ = storage.update_chapter_note(&chapter.id, None, "error", Some(&err));
                    update_job(&jobs_state, &thread_id, "error", 100, Some(&err));
                }
            }
        });

        Ok(self
            .jobs
            .lock()
            .map_err(|e| e.to_string())?
            .get(&id)
            .cloned()
            .ok_or_else(|| "任务创建失败".to_string())?)
    }

    fn active_jobs(&self) -> Result<Vec<Job>, String> {
        let jobs = self.jobs.lock().map_err(|e| e.to_string())?;
        Ok(jobs
            .values()
            .filter(|j| j.status == "queued" || j.status == "running")
            .cloned()
            .collect())
    }

    fn find_active_for_chapter(&self, chapter_id: &str) -> Result<Option<String>, String> {
        let jobs = self.jobs.lock().map_err(|e| e.to_string())?;
        for job in jobs.values() {
            if job.chapter_id == chapter_id && (job.status == "queued" || job.status == "running") {
                return Ok(Some(job.id.clone()));
            }
        }
        Ok(None)
    }
}

fn update_job(
    jobs: &Mutex<HashMap<String, Job>>,
    id: &str,
    status: &str,
    progress: u8,
    error: Option<&str>,
) {
    if let Ok(mut jobs) = jobs.lock() {
        if let Some(job) = jobs.get_mut(id) {
            job.status = status.to_string();
            job.progress = progress;
            job.error = error.map(|s| s.to_string());
        }
    }
}

#[tauri::command]
pub fn list_books(state: State<'_, AppState>) -> Result<Vec<BookSummary>, String> {
    state.storage.list_books()
}

#[tauri::command]
pub fn get_book(book_id: String, state: State<'_, AppState>) -> Result<BookDetail, String> {
    state.storage.get_book(&book_id)
}

#[tauri::command]
pub async fn import_path(path: String, state: State<'_, AppState>) -> Result<BookDetail, String> {
    let storage = state.storage.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let path = Path::new(&path);
        if !path.exists() {
            return Err("文件不存在".into());
        }
        let text = chapters::read_text(path)?;
        let chapters = chapters::split_chapters(&text);
        if chapters.is_empty() {
            return Err("未能识别到章节，请检查 TXT 是否包含章节标题".into());
        }

        let title = path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_else(|| "未命名书籍".into());

        let rows: Vec<(i64, String, String)> = chapters
            .iter()
            .map(|ch| (ch.idx, ch.title.clone(), ch.text.clone()))
            .collect();

        storage.add_book(&title, "", &path.to_string_lossy(), &rows)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub fn delete_book(book_id: String, state: State<'_, AppState>) -> Result<(), String> {
    state.storage.delete_book(&book_id)
}

#[tauri::command]
pub fn generate_chapter(
    book_id: String,
    chapter_id: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let book = state.storage.get_book(&book_id)?;
    if book.chapters.iter().all(|c| c.id != chapter_id) {
        return Err("章节不存在".into());
    }
    if let Some(job_id) = state.find_active_for_chapter(&chapter_id)? {
        return Ok(job_id);
    }
    let row = state
        .storage
        .chapter_row(&chapter_id)?
        .ok_or_else(|| "章节不存在".to_string())?;
    let job = state.submit_job(book_id, row)?;
    Ok(job.id)
}

#[tauri::command]
pub fn generate_all(book_id: String, state: State<'_, AppState>) -> Result<Vec<Job>, String> {
    let book = state.storage.get_book(&book_id)?;
    let mut jobs = Vec::new();
    for chapter in &book.chapters {
        if chapter.status == "done" {
            continue;
        }
        if state.find_active_for_chapter(&chapter.id)?.is_some() {
            continue;
        }
        let row = state
            .storage
            .chapter_row(&chapter.id)?
            .ok_or_else(|| "章节不存在".to_string())?;
        let job = state.submit_job(book_id.clone(), row)?;
        jobs.push(job);
    }
    Ok(jobs)
}

#[tauri::command]
pub fn list_jobs(state: State<'_, AppState>) -> Result<Vec<Job>, String> {
    state.active_jobs()
}

#[tauri::command]
pub fn get_settings(state: State<'_, AppState>) -> Result<Settings, String> {
    state.storage.get_settings()
}

#[tauri::command]
pub fn save_settings(
    settings: Settings,
    state: State<'_, AppState>,
) -> Result<Settings, String> {
    state.storage.save_settings(&settings)?;
    Ok(settings)
}

#[tauri::command]
pub fn pick_file() -> Option<String> {
    rfd::FileDialog::new()
        .add_filter("TXT 小说", &["txt"])
        .pick_file()
        .map(|p| p.to_string_lossy().into_owned())
}
