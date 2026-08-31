# Contract — 工具 JSON Schema

工具是「模型 ↔ agent」之间的接口契约。每个工具 = `name` + `description` + `input_schema`（传给模型的 `tools` 参数），handler 负责本地执行并返回结果文本。

## read_file

读取指定文件内容。

```json
{
  "name": "read_file",
  "description": "读取一个文本文件的内容。路径相对于工作目录。",
  "parameters": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "文件路径" },
      "offset": { "type": "integer", "description": "起始行（1 起）" },
      "limit": { "type": "integer", "description": "读取行数" }
    },
    "required": ["path"]
  }
}
```

## write_file

写入（覆盖）文件。

```json
{
  "name": "write_file",
  "description": "创建或整体覆盖一个文件。路径必须在工作目录内。",
  "parameters": {
    "type": "object",
    "properties": {
      "path": { "type": "string" },
      "content": { "type": "string" }
    },
    "required": ["path", "content"]
  }
}
```

## edit_file

按 `old_string` → `new_string` 做唯一匹配的精准替换（类 Claude Code Edit）。

```json
{
  "name": "edit_file",
  "description": "将文件中唯一出现的一段文本替换为新文本。old_string 必须精确匹配。",
  "parameters": {
    "type": "object",
    "properties": {
      "path": { "type": "string" },
      "old_string": { "type": "string" },
      "new_string": { "type": "string" },
      "replace_all": { "type": "boolean", "description": "替换所有匹配（默认 false）" }
    },
    "required": ["path", "old_string", "new_string"]
  }
}
```

## apply_patch

应用 unified diff 补丁（可选加分项，支持多 hunk）。

```json
{
  "name": "apply_patch",
  "description": "对工作目录应用 unified diff 补丁。",
  "parameters": {
    "type": "object",
    "properties": { "patch": { "type": "string" } },
    "required": ["patch"]
  }
}
```

## list_dir

列出目录内容。

```json
{
  "name": "list_dir",
  "description": "列出目录下的条目。",
  "parameters": {
    "type": "object",
    "properties": { "path": { "type": "string" } },
    "required": ["path"]
  }
}
```

## glob

按文件名通配模式搜索文件。

```json
{
  "name": "glob",
  "description": "按 glob 模式（如 **/*.py）查找文件路径。",
  "parameters": {
    "type": "object",
    "properties": { "pattern": { "type": "string" } },
    "required": ["pattern"]
  }
}
```

## grep

按正则搜索文件内容（对齐 ripgrep 用法）。

```json
{
  "name": "grep",
  "description": "在工作目录内按正则搜索文件内容，返回匹配行与文件位置。",
  "parameters": {
    "type": "object",
    "properties": {
      "pattern": { "type": "string" },
      "path": { "type": "string", "description": "限定目录（可选）" },
      "glob": { "type": "string", "description": "限定文件类型（可选）" }
    },
    "required": ["pattern"]
  }
}
```

## bash

执行 shell 命令。

```json
{
  "name": "bash",
  "description": "在工作目录内执行 shell 命令，返回 stdout/stderr 与退出码。破坏性命令需用户确认。",
  "parameters": {
    "type": "object",
    "properties": {
      "command": { "type": "string" },
      "timeout": { "type": "integer", "description": "超时秒数（默认 120）" }
    },
    "required": ["command"]
  }
}
```

## todo_write

维护任务清单（规划记忆）。

```json
{
  "name": "todo_write",
  "description": "更新任务清单：列出计划、标记进行中/完成。",
  "parameters": {
    "type": "object",
    "properties": {
      "todos": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "id": { "type": "integer" },
            "content": { "type": "string" },
            "status": { "enum": ["pending", "in_progress", "completed"] }
          },
          "required": ["id", "content", "status"]
        }
      }
    },
    "required": ["todos"]
  }
}
```
