use std::collections::HashMap;
use std::path::Path;

use encoding_rs::{BIG5, GBK, UTF_16BE, UTF_16LE};
use regex::Regex;

#[derive(Debug, Clone)]
pub struct Chapter {
    pub idx: i64,
    pub title: String,
    pub text: String,
}

pub fn read_text(path: &Path) -> Result<String, String> {
    let data = std::fs::read(path).map_err(|e| e.to_string())?;
    Ok(decode_bytes(&data))
}

fn decode_bytes(data: &[u8]) -> String {
    // BOM
    if data.starts_with(&[0xEF, 0xBB, 0xBF]) {
        return String::from_utf8_lossy(&data[3..]).into_owned();
    }
    if data.starts_with(&[0xFF, 0xFE]) {
        return UTF_16LE.decode(&data[2..]).0.into_owned();
    }
    if data.starts_with(&[0xFE, 0xFF]) {
        return UTF_16BE.decode(&data[2..]).0.into_owned();
    }

    if let Ok(s) = std::str::from_utf8(data) {
        return s.to_string();
    }

    for (encoding, name) in [
        (GBK, "gbk"),
        (BIG5, "big5"),
        (UTF_16LE, "utf16le"),
        (UTF_16BE, "utf16be"),
    ] {
        let (cow, _, had_errors) = encoding.decode(data);
        if !had_errors {
            let _ = name;
            return cow.into_owned();
        }
    }

    String::from_utf8_lossy(data).into_owned()
}

fn normalize_newlines(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}

pub fn split_chapters(text: &str) -> Vec<Chapter> {
    let text = normalize_newlines(text);
    let lines: Vec<&str> = text.split('\n').collect();

    let pattern = Regex::new(
        r"(?i)^\s*(?:第\s*[0-9０-９一二三四五六七八九十百千万零〇]+\s*[章回节](?:\s*[:：、.\-—]?\s*.*)?|(?:chapter|第)\s+(?:[0-9]+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*[:：.\-—]?\s*.*)?|序章|序言|楔子|引子|前言|尾声|后记|终章|最终章|间章|番外(?:\s*[0-9一二三四五六七八九十百千]+)?(?:\s*[:：.\-—]?\s*.*)?|外传(?:\s*[0-9一二三四五六七八九十百千]+)?(?:\s*[:：.\-—]?\s*.*)?)\s*$",
    )
    .expect("invalid chapter regex");

    let mut candidates: Vec<(usize, String)> = Vec::new();
    for (idx, line) in lines.iter().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.chars().count() > 80 {
            continue;
        }
        if trimmed
            .chars()
            .last()
            .map_or(false, |c| matches!(c, '。' | '！' | '？' | '；' | '，' | '：' | '、'))
        {
            continue;
        }
        if pattern.is_match(trimmed) {
            candidates.push((idx, trimmed.to_string()));
        }
    }

    if candidates.is_empty() {
        return fallback_chapters(&lines);
    }

    let filtered = filter_toc(candidates, &lines);
    if filtered.is_empty() {
        return fallback_chapters(&lines);
    }

    let mut chapters = Vec::new();
    let mut next_idx = 1i64;
    for (pos, (start, title)) in filtered.iter().enumerate() {
        let end = if pos + 1 < filtered.len() {
            filtered[pos + 1].0.saturating_sub(1)
        } else {
            lines.len().saturating_sub(1)
        };
        let chapter_text = lines[*start..=end].join("\n").trim().to_string();
        if chapter_text.is_empty() {
            continue;
        }
        chapters.push(Chapter {
            idx: next_idx,
            title: title.clone(),
            text: chapter_text,
        });
        next_idx += 1;
    }

    if chapters.is_empty() {
        vec![Chapter {
            idx: 1,
            title: "全文".into(),
            text: text.trim().to_string(),
        }]
    } else {
        chapters
    }
}

fn fallback_chapters(lines: &[&str]) -> Vec<Chapter> {
    const CHUNK_LINES: usize = 800;
    let mut chapters = Vec::new();
    let mut idx = 1i64;
    for chunk in lines.chunks(CHUNK_LINES) {
        let text = chunk.join("\n").trim().to_string();
        if text.is_empty() {
            continue;
        }
        chapters.push(Chapter {
            idx,
            title: format!("第{}部分", idx),
            text,
        });
        idx += 1;
    }
    chapters
}

fn filter_toc(
    candidates: Vec<(usize, String)>,
    lines: &[&str],
) -> Vec<(usize, String)> {
    if candidates.len() < 3 {
        return candidates;
    }

    // 收集“连续标题块”：中间没有非空正文行的标题视为同一块。
    let candidate_lines: std::collections::HashSet<usize> =
        candidates.iter().map(|(i, _)| *i).collect();
    let mut runs: Vec<Vec<(usize, String)>> = Vec::new();
    let mut current = vec![candidates[0].clone()];
    for pair in candidates.windows(2) {
        let prev = &pair[0];
        let cur = &pair[1];
        let gap = cur.0.saturating_sub(prev.0).saturating_sub(1);
        let has_separator = lines[prev.0 + 1..cur.0].iter().enumerate().any(|(offset, line)| {
            let real_idx = prev.0 + 1 + offset;
            !line.trim().is_empty() && !candidate_lines.contains(&real_idx)
        });
        if gap <= 10 && !has_separator {
            current.push(cur.clone());
        } else {
            runs.push(std::mem::take(&mut current));
            current.push(cur.clone());
        }
    }
    runs.push(current);

    // 策略 1：重复标题出现时，丢掉“后面还会出现”的目录块。
    let mut title_counts: HashMap<&str, usize> = HashMap::new();
    for (_, title) in &candidates {
        *title_counts.entry(title.as_str()).or_insert(0) += 1;
    }
    let has_duplicates = title_counts.values().any(|count| *count > 1);
    if has_duplicates {
        let mut kept: Vec<(usize, String)> = Vec::new();
        for (run_idx, run) in runs.iter().enumerate() {
            let later_titles: std::collections::HashSet<&str> = runs[run_idx + 1..]
                .iter()
                .flat_map(|later| later.iter().map(|(_, t)| t.as_str()))
                .collect();
            let all_in_later = run.len() >= 2
                && run.iter().all(|(_, title)| {
                    title_counts.get(title.as_str()).copied().unwrap_or(0) > 1
                        && later_titles.contains(title.as_str())
                });
            if !all_in_later {
                kept.extend(run.iter().cloned());
            }
        }
        if !kept.is_empty() {
            return kept;
        }
    }

    // 策略 2：没有重复时，丢弃长正文之前的大块目录；全丢则保留最后一块。
    let first_body = lines.iter().position(|line| line.trim().chars().count() > 50);
    let mut kept: Vec<(usize, String)> = Vec::new();
    for run in &runs {
        let run_end = run.last().map(|(i, _)| *i).unwrap_or(0);
        let looks_like_toc = run.len() >= 3
            && (first_body.is_none() || run_end < first_body.unwrap());
        if !looks_like_toc {
            kept.extend(run.iter().cloned());
        }
    }
    if kept.is_empty() {
        if let Some(last) = runs.last() {
            return last.clone();
        }
    }
    kept
}
