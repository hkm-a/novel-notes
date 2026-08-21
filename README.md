# novel-notes

把一本 TXT 小说按章节自动生成结构化读书笔记。支持本地 Ollama / OpenAI 兼容接口，长章节自动分片摘要再合并，中断后可续跑。

## 功能

- **Tauri 桌面应用**：原生窗口、拖拽导入 TXT、按书籍分类、逐章生成笔记、可视化进度
- **章节识别**：自动匹配中文网文标题（`第一章`、`第1章`、`序章`、`番外` 等）和英文 `Chapter N`
- **目录过滤**：自动跳过常见“目录页”误切分
- **健壮输入**：自动检测 UTF-8 / GB18030 / Big5 / UTF-16 等编码
- **结构化笔记**：每章输出摘要、主要人物、剧情推进、伏笔、关键台词、本章疑问
- **长章节处理**：超过阈值自动 Map-Reduce，先分片摘要再合并
- **失败重试**：网络超时、5xx、限流自动指数退避重试
- **断点续跑**：进度保存在 `.progress.json`，中断后不会重复生成已完成章节
- **并发可选**：`--workers N` 控制并发请求数
- **纯切分模式**：`split` 子命令可以只切分章节，不调用 LLM

## 安装

```bash
pip install -r requirements.txt
# 或
pip install -e .
```

## 快速开始

### OpenAI 兼容 API

```bash
export OPENAI_API_KEY="sk-..."
novel-notes generate 小说.txt \
  --base-url https://api.openai.com/v1 \
  --model gpt-4o-mini \
  -o notes
```

### 本地 Ollama

```bash
# 先启动 Ollama 并拉取模型
# ollama pull qwen2.5:7b

novel-notes generate 小说.txt \
  --base-url http://localhost:11434/v1 \
  --api-key ollama \
  --model qwen2.5:7b \
  -o notes
```

### 只切分章节

```bash
novel-notes split 小说.txt -o chapters
```

切分结果会同时生成 `chapters.json`，方便后续自己接其他工具。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--model` | 模型名，默认 `gpt-4o-mini` |
| `--base-url` | OpenAI 兼容地址，默认 `https://api.openai.com/v1` |
| `--api-key` | API Key，默认读 `OPENAI_API_KEY` |
| `--max-chunk-chars` | 超过该字符数启用长章节分片，默认 6000 |
| `--workers` | 并发数，默认 1 |
| `--force` | 重新生成已完成章节 |
| `--no-continue-on-error` | 某章失败立即停止（默认继续并写错误文件） |
| `--single-file` | 额外输出一个合并版 Markdown |
| `--dry-run` | 只打印章节切分结果，不调用模型 |
| `--chapter-pattern` | 自定义章节标题正则 |

更多参数见 `novel-notes generate --help`。

## 输出结构

```
notes/
├── index.md               # 总目录/索引
├── .progress.json         # 断点续跑进度
├── 0001_第一章 XXX.md
├── 0002_第二章 XXX.md
└── ...
```

每章笔记格式：

```markdown
## 一句话概括

## 本章摘要

## 主要人物

## 剧情推进 / 关键事件

## 伏笔 / 线索

## 关键台词

## 本章疑问
```

## 开发

```bash
python -m pytest
```


## Tauri 桌面应用（推荐）

本项目现在同时保留 Python CLI，并新增了一个 **Tauri 桌面应用**（不依赖浏览器、不启动 Web 服务）。

桌面端支持：

- 拖拽 TXT 小说到窗口直接导入
- 自动识别章节并按书籍分类展示
- 每个章节都有独立的“生成笔记”按钮
- 支持“生成全部笔记”
- 可视化进度、笔记预览、失败提示
- 在界面里直接配置 AI 模型（默认 `agnes`）
- Rust 后端直接调用 OpenAI 兼容接口，无 Python 运行时依赖

启动开发版：

```bash
cd src-tauri
cargo run
```

打包安装包：

```bash
cd src-tauri
cargo tauri build
# 或安装 npm 版 CLI 后：npm run tauri build
```

> 桌面端数据保存在系统应用数据目录下的 `Novel Notes/library.db`。

### 默认 AI 配置

桌面端默认使用：

- 模型：`agnes`
- 接口：`http://localhost:11434/v1`（Ollama 风格）
- API Key：`ollama`

如果 `agnes` 不是本地 Ollama 模型名，或者你用的是云端 API，打开右上角“模型设置”修改即可。
