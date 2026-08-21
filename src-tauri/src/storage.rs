use std::path::Path;
use std::sync::Mutex;

use chrono::Local;
use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub temperature: f64,
    pub max_tokens: u32,
    pub timeout: f64,
    pub max_retries: u32,
    pub max_chunk_chars: usize,
    pub chunk_overlap: usize,
    pub workers: usize,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            base_url: "http://localhost:11434/v1".into(),
            api_key: "ollama".into(),
            model: "agnes".into(),
            temperature: 0.3,
            max_tokens: 2000,
            timeout: 120.0,
            max_retries: 5,
            max_chunk_chars: 6000,
            chunk_overlap: 200,
            workers: 1,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct BookSummary {
    pub id: String,
    pub title: String,
    pub author: String,
    pub source_path: String,
    pub created_at: String,
    pub updated_at: String,
    pub chapter_count: i64,
    pub done_count: i64,
    pub error_count: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Chapter {
    pub id: String,
    pub book_id: String,
    pub idx: i64,
    pub title: String,
    pub char_count: i64,
    pub note: Option<String>,
    pub status: String,
    pub error: Option<String>,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct BookDetail {
    pub id: String,
    pub title: String,
    pub author: String,
    pub source_path: String,
    pub created_at: String,
    pub updated_at: String,
    pub chapter_count: i64,
    pub done_count: i64,
    pub error_count: i64,
    pub chapters: Vec<Chapter>,
}

#[derive(Debug, Clone)]
pub struct ChapterRow {
    pub id: String,
    pub title: String,
    pub text: String,
}

pub struct Storage {
    conn: Mutex<Connection>,
}

fn now() -> String {
    Local::now().format("%Y-%m-%dT%H:%M:%S%:z").to_string()
}

impl Storage {
    pub fn open(path: &Path) -> Result<Self, String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let conn = Connection::open(path).map_err(|e| e.to_string())?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );",
        )
        .map_err(|e| e.to_string())?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub fn add_book(
        &self,
        title: &str,
        author: &str,
        source_path: &str,
        chapters: &[(i64, String, String)],
    ) -> Result<BookDetail, String> {
        let id = Uuid::new_v4().simple().to_string()[..12].to_string();
        let ts = now();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;

        conn.execute(
            "INSERT INTO books (id, title, author, source_path, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            rusqlite::params![id, title, author, source_path, ts, ts],
        )
        .map_err(|e| e.to_string())?;

        {
            let mut stmt = conn
                .prepare(
                    "INSERT INTO chapters (id, book_id, idx, title, text, char_count, status, updated_at)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'pending', ?7)",
                )
                .map_err(|e| e.to_string())?;
            for (idx, ch_title, text) in chapters {
                let ch_id = Uuid::new_v4().simple().to_string()[..12].to_string();
                stmt.execute(rusqlite::params![
                    ch_id,
                    id,
                    idx,
                    ch_title,
                    text,
                    text.chars().count() as i64,
                    ts
                ])
                .map_err(|e| e.to_string())?;
            }
        }

        drop(conn);
        self.get_book(&id)
    }

    pub fn list_books(&self) -> Result<Vec<BookSummary>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT b.id, b.title, b.author, b.source_path, b.created_at, b.updated_at,
                        COUNT(c.id) AS chapter_count,
                        COALESCE(SUM(CASE WHEN c.status = 'done' THEN 1 ELSE 0 END), 0) AS done_count,
                        COALESCE(SUM(CASE WHEN c.status = 'error' THEN 1 ELSE 0 END), 0) AS error_count
                 FROM books b
                 LEFT JOIN chapters c ON c.book_id = b.id
                 GROUP BY b.id
                 ORDER BY b.created_at DESC",
            )
            .map_err(|e| e.to_string())?;

        let rows = stmt
            .query_map([], |row| {
                Ok(BookSummary {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    author: row.get(2)?,
                    source_path: row.get(3)?,
                    created_at: row.get(4)?,
                    updated_at: row.get(5)?,
                    chapter_count: row.get(6)?,
                    done_count: row.get(7)?,
                    error_count: row.get(8)?,
                })
            })
            .map_err(|e| e.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        Ok(rows)
    }

    pub fn get_book(&self, id: &str) -> Result<BookDetail, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let row = conn
            .query_row(
                "SELECT b.id, b.title, b.author, b.source_path, b.created_at, b.updated_at,
                        COUNT(c.id) AS chapter_count,
                        COALESCE(SUM(CASE WHEN c.status = 'done' THEN 1 ELSE 0 END), 0) AS done_count,
                        COALESCE(SUM(CASE WHEN c.status = 'error' THEN 1 ELSE 0 END), 0) AS error_count
                 FROM books b
                 LEFT JOIN chapters c ON c.book_id = b.id
                 WHERE b.id = ?1
                 GROUP BY b.id",
                [id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, i64>(6)?,
                        row.get::<_, i64>(7)?,
                        row.get::<_, i64>(8)?,
                    ))
                },
            )
            .optional()
            .map_err(|e| e.to_string())?;

        let Some((id, title, author, source_path, created_at, updated_at, chapter_count, done_count, error_count)) = row else {
            return Err("书籍不存在".into());
        };

        let chapters = {
            let mut stmt = conn
                .prepare(
                    "SELECT id, book_id, idx, title, char_count, note, status, error, updated_at
                     FROM chapters WHERE book_id = ?1 ORDER BY idx ASC",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map([&id], |row| {
                    Ok(Chapter {
                        id: row.get(0)?,
                        book_id: row.get(1)?,
                        idx: row.get(2)?,
                        title: row.get(3)?,
                        char_count: row.get(4)?,
                        note: row.get(5)?,
                        status: row.get(6)?,
                        error: row.get(7)?,
                        updated_at: row.get(8)?,
                    })
                })
                .map_err(|e| e.to_string())?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?;
            rows
        };

        Ok(BookDetail {
            id,
            title,
            author,
            source_path,
            created_at,
            updated_at,
            chapter_count,
            done_count,
            error_count,
            chapters,
        })
    }

    pub fn delete_book(&self, id: &str) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute("DELETE FROM books WHERE id = ?1", [id])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn chapter_row(&self, id: &str) -> Result<Option<ChapterRow>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let row = conn
            .query_row(
                "SELECT id, title, text FROM chapters WHERE id = ?1",
                [id],
                |row| {
                    Ok(ChapterRow {
                        id: row.get(0)?,
                        title: row.get(1)?,
                        text: row.get(2)?,
                    })
                },
            )
            .optional()
            .map_err(|e| e.to_string())?;
        Ok(row)
    }

    pub fn update_chapter_note(
        &self,
        chapter_id: &str,
        note: Option<&str>,
        status: &str,
        error: Option<&str>,
    ) -> Result<(), String> {
        let ts = now();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE chapters SET note = ?1, status = ?2, error = ?3, updated_at = ?4 WHERE id = ?5",
            rusqlite::params![note, status, error, ts, chapter_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn get_settings(&self) -> Result<Settings, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare("SELECT key, value FROM settings")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))
            .map_err(|e| e.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        let mut settings = Settings::default();
        for (key, value) in rows {
            let parsed: serde_json::Value = serde_json::from_str(&value).unwrap_or(serde_json::Value::Null);
            match key.as_str() {
                "base_url" => {
                    if let Some(v) = parsed.as_str() {
                        settings.base_url = v.to_string();
                    }
                }
                "api_key" => {
                    if let Some(v) = parsed.as_str() {
                        settings.api_key = v.to_string();
                    }
                }
                "model" => {
                    if let Some(v) = parsed.as_str() {
                        settings.model = v.to_string();
                    }
                }
                "temperature" => {
                    if let Some(v) = parsed.as_f64() {
                        settings.temperature = v;
                    }
                }
                "max_tokens" => {
                    if let Some(v) = parsed.as_u64() {
                        settings.max_tokens = v as u32;
                    }
                }
                "timeout" => {
                    if let Some(v) = parsed.as_f64() {
                        settings.timeout = v;
                    }
                }
                "max_retries" => {
                    if let Some(v) = parsed.as_u64() {
                        settings.max_retries = v as u32;
                    }
                }
                "max_chunk_chars" => {
                    if let Some(v) = parsed.as_u64() {
                        settings.max_chunk_chars = v as usize;
                    }
                }
                "chunk_overlap" => {
                    if let Some(v) = parsed.as_u64() {
                        settings.chunk_overlap = v as usize;
                    }
                }
                "workers" => {
                    if let Some(v) = parsed.as_u64() {
                        settings.workers = v as usize;
                    }
                }
                _ => {}
            }
        }
        Ok(settings)
    }

    pub fn save_settings(&self, settings: &Settings) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare("INSERT OR REPLACE INTO settings (key, value) VALUES (?1, ?2)")
            .map_err(|e| e.to_string())?;
        let pairs = [
            ("base_url", serde_json::json!(settings.base_url).to_string()),
            ("api_key", serde_json::json!(settings.api_key).to_string()),
            ("model", serde_json::json!(settings.model).to_string()),
            ("temperature", serde_json::json!(settings.temperature).to_string()),
            ("max_tokens", serde_json::json!(settings.max_tokens).to_string()),
            ("timeout", serde_json::json!(settings.timeout).to_string()),
            ("max_retries", serde_json::json!(settings.max_retries).to_string()),
            ("max_chunk_chars", serde_json::json!(settings.max_chunk_chars).to_string()),
            ("chunk_overlap", serde_json::json!(settings.chunk_overlap).to_string()),
            ("workers", serde_json::json!(settings.workers).to_string()),
        ];
        for (key, value) in pairs {
            stmt.execute(rusqlite::params![key, value])
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}
