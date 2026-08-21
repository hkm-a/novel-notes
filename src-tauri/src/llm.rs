use std::thread;
use std::time::Duration;

use reqwest::blocking::Client;
use reqwest::StatusCode;
use serde_json::json;

use crate::storage::Settings;

const SYSTEM_PROMPT: &str = "你是一个专业的小说读书笔记助手。你的任务是根据用户提供的小说章节原文，生成结构清晰、忠实原文的 Markdown 读书笔记。\n\n要求：\n1. 使用简体中文。\n2. 只输出笔记本身，不要输出寒暄，不要复述原文。\n3. 严格基于原文，不要编造原文中没有出现的人物、情节或台词。\n4. 如果某项确实没有内容，写“无”或“暂无”。\n5. 保持输出格式稳定，方便后续整理。\n";

const MEMORY_SYSTEM_PROMPT: &str = "你是一个小说全书记忆管理员。你的任务是把前面的章节笔记浓缩成一份持续更新的全局记忆，用于后续章节生成时保持剧情连贯。\n\n要求：\n1. 使用简体中文。\n2. 重点保留：主要人物及关系、剧情主线、重要事件、伏笔/悬念、未解决问题、重要设定。\n3. 删除已经结束的临时细节，保留长期有效信息。\n4. 输出简洁的结构化 Markdown，控制在 800 字以内。\n5. 只输出更新后的记忆内容，不要解释。\n";

pub fn generate_chapter_note(
    settings: &Settings,
    title: &str,
    text: &str,
    context: &[String],
) -> Result<String, String> {
    let context_block = build_context_block(context);

    if text.chars().count() <= settings.max_chunk_chars {
        let user = format!(
            "请阅读以下小说章节原文，并生成结构化读书笔记。\n\n【章节标题】\n{}\n\n{}【原文】\n{}",
            title, context_block, text
        );
        return chat_completion(settings, SYSTEM_PROMPT, &user);
    }

    let chunks = split_text_into_chunks(text, settings.max_chunk_chars, settings.chunk_overlap);
    let mut summaries = Vec::new();
    for (i, chunk) in chunks.iter().enumerate() {
        let user = format!(
            "下面是小说的一个章节片段。请生成该片段的简明摘要。\n\n【章节标题】\n{}\n\n{}【片段位置】\n第 {} / {} 个片段\n\n【片段原文】\n{}\n\n请输出以下内容（Markdown 格式）：\n- 本片段涉及的主要人物\n- 本片段发生的关键事件\n- 出现的伏笔、线索或悬念\n- 值得记住的台词（如有）\n- 一句话概括本片段\n\n不要输出完整章节笔记，只输出这个片段的摘要。",
            title,
            context_block,
            i + 1,
            chunks.len(),
            chunk
        );
        summaries.push(chat_completion(settings, SYSTEM_PROMPT, &user)?);
    }

    let joined = summaries
        .iter()
        .enumerate()
        .map(|(i, s)| format!("### 片段 {}\n\n{}", i + 1, s.trim()))
        .collect::<Vec<_>>()
        .join("\n\n---\n\n");

    let user = format!(
        "下面是某小说章节的分片摘要。请把这些摘要综合成一份完整的章节读书笔记。\n\n【章节标题】\n{}\n\n{}【分片摘要】\n{}\n\n请按以下固定结构输出 Markdown：\n\n## 一句话概括\n\n## 本章摘要\n\n## 主要人物\n\n## 剧情推进 / 关键事件\n\n## 伏笔 / 线索\n\n## 关键台词\n\n## 本章疑问\n\n要求：\n- 把各分片的信息合并、去重、按时间顺序整理。\n- 结合前情提要，保持人物关系、剧情发展和伏笔的连贯性。\n- 不要编造分片摘要或前情提要中没有的内容。\n- 某项没有内容时写“无”或“暂无”。",
        title, context_block, joined
    );
    chat_completion(settings, SYSTEM_PROMPT, &user)
}

fn build_context_block(context: &[String]) -> String {
    if context.is_empty() {
        return String::new();
    }
    let joined = context.join("\n\n---\n\n");
    format!("【前情提要（之前章节的笔记摘要）】\n{}\n\n", joined)
}

pub fn update_book_memory(
    settings: &Settings,
    book_title: &str,
    previous_memory: &str,
    chapter_note: &str,
) -> Result<String, String> {
    let user = format!(
        "请根据已有全局记忆和最新一章的笔记，更新这本小说的全局记忆。\n\n【书名】\n{}\n\n【已有全局记忆】\n{}\n\n【最新一章笔记】\n{}\n\n请输出更新后的全局记忆，不要输出其他内容。",
        book_title,
        if previous_memory.is_empty() { "（暂无）" } else { previous_memory },
        chapter_note
    );
    chat_completion(settings, MEMORY_SYSTEM_PROMPT, &user)
}

pub fn split_text_into_chunks(text: &str, max_chars: usize, overlap_chars: usize) -> Vec<String> {
    if text.chars().count() <= max_chars || max_chars == 0 {
        return vec![text.to_string()];
    }

    let chars: Vec<char> = text.chars().collect();
    let mut chunks = Vec::new();
    let mut start = 0usize;
    let text_len = chars.len();

    while start < text_len {
        let mut end = (start + max_chars).min(text_len);
        // 尽量在换行处断开
        let window = &chars[start..end];
        if let Some(rel) = window.iter().rposition(|c| *c == '\n') {
            if rel > max_chars / 2 {
                end = start + rel + 1;
            }
        }
        let chunk: String = chars[start..end].iter().collect();
        if !chunk.trim().is_empty() {
            chunks.push(chunk.trim().to_string());
        }
        if end >= text_len {
            break;
        }
        let next_start = end.saturating_sub(overlap_chars).max(start + 1);
        start = next_start;
    }

    chunks.into_iter().filter(|c| !c.trim().is_empty()).collect()
}

fn chat_completion(settings: &Settings, system: &str, user: &str) -> Result<String, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs_f64(settings.timeout.max(1.0)))
        .build()
        .map_err(|e| e.to_string())?;

    let base = settings.base_url.trim_end_matches('/');
    let endpoint = if base.ends_with("/chat/completions") {
        base.to_string()
    } else {
        format!("{}/chat/completions", base)
    };

    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert(
        "Content-Type",
        reqwest::header::HeaderValue::from_static("application/json"),
    );
    if !settings.api_key.is_empty() {
        headers.insert(
            "Authorization",
            reqwest::header::HeaderValue::from_str(&format!("Bearer {}", settings.api_key))
                .map_err(|e| e.to_string())?,
        );
    }

    let payload = json!({
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": settings.temperature,
        "stream": false,
        "max_tokens": settings.max_tokens,
    });

    let max_retries = settings.max_retries.max(1) as usize;
    let mut last_err = String::from("未知错误");

    for attempt in 0..=max_retries {
        match client.post(&endpoint).headers(headers.clone()).json(&payload).send() {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    return extract_content(resp);
                }
                let body = resp.text().unwrap_or_default();
                let msg = format!("HTTP {}: {}", status, truncate(&body, 500));
                if is_retryable(status) {
                    last_err = msg.clone();
                    if attempt < max_retries {
                        let delay = (2u64.pow(attempt as u32)).min(60) as u64;
                        thread::sleep(Duration::from_secs(delay));
                        continue;
                    }
                }
                return Err(msg);
            }
            Err(e) => {
                last_err = e.to_string();
                if attempt < max_retries {
                    let delay = (2u64.pow(attempt as u32)).min(60) as u64;
                    thread::sleep(Duration::from_secs(delay));
                }
            }
        }
    }

    Err(format!("LLM 调用失败: {}", last_err))
}

fn is_retryable(status: StatusCode) -> bool {
    matches!(
        status,
        StatusCode::REQUEST_TIMEOUT
            | StatusCode::TOO_MANY_REQUESTS
            | StatusCode::INTERNAL_SERVER_ERROR
            | StatusCode::BAD_GATEWAY
            | StatusCode::SERVICE_UNAVAILABLE
            | StatusCode::GATEWAY_TIMEOUT
    )
}

fn extract_content(resp: reqwest::blocking::Response) -> Result<String, String> {
    let data: serde_json::Value = resp.json().map_err(|e| e.to_string())?;
    let content = data
        .pointer("/choices/0/message/content")
        .and_then(|v| v.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            format!(
                "模型返回内容为空或格式异常: {}",
                truncate(&data.to_string(), 500)
            )
        })?;
    Ok(content)
}

fn truncate(s: &str, max: usize) -> String {
    let chars: Vec<char> = s.chars().collect();
    if chars.len() <= max {
        s.to_string()
    } else {
        chars[..max].iter().collect::<String>() + "..."
    }
}
