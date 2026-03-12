---
description: AI 调试与临时文件存储规范
---

# 调试与临时文件使用规范 (Debug & Temp Files Convention)

## 核心原则
在进行代码调试、错误排查、输出重定向或临时数据分析时，**严禁将临时文件、日志文件和测试桩直接写入项目根目录或其他源码目录**，以避免污染项目结构和版本控制。

## 标准目录
所有针对当前任务生成的中间数据、命令行重定向输出、调试日志（如 `curl` 分析、`cargo` 或 `python` 的错误输出重定向、临时 JSON 检查），必须统一存放在：
**`.debug/`** 目录中。

## 规范细则
1. **自动创建**：如果 `.debug/` 目录不存在，应该在执行任何产生临时文件的终端操作前，主动使用 `mkdir` 创建该文件夹。
2. **命名语义**：在 `.debug/` 内创建的文件，尽可能带有时间标识或操作语义前缀（如 `.debug/build_errors_v3.txt`, `.debug/gemini_stream_chunk.json`），以便于后续复查或清理。
3. **版本控制**：`.debug/` 目录默认应该保持被添加到项目的 `.gitignore` 中（只在首次检查缺失时主动追加 `echo ".debug/" >> .gitignore`）。
4. **清理职责**：该目录下的文件对项目的运行完全不产生依赖，当排查任务结束时，可以直接废弃，不需要去维护其内容。

## 适用场景（示例）
- `cargo check > .debug/check.log 2>&1`
- `python script.py > .debug/test_output.txt`
- 创建一个临时的 `reqwest` response mock 数据: `.debug/mock_gemini_resp.json`
