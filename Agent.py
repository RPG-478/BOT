#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A small, safe, Manus-like terminal agent for this repository.

Examples:
  python Agent.py "このリポジトリの構成を調べて"
  python Agent.py --interactive
  python Agent.py "テストを実行して結果を要約" --max-turns 6

The LLM is optional. Without GROQ_API_KEY, the CLI still supports local
inspection commands and produces a useful deterministic report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

ROOT = Path(__file__).resolve().parent
DEFAULT_IGNORES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
MAX_READ = 20000


def safe_path(raw: str) -> Path:
    candidate = (ROOT / raw).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError("作業ディレクトリ外のパスは扱えません。")
    return candidate


def list_files(path: str = ".") -> str:
    base = safe_path(path)
    if not base.is_dir():
        return f"ディレクトリではありません: {path}"
    files = []
    for item in sorted(base.rglob("*")):
        if any(part in DEFAULT_IGNORES for part in item.parts):
            continue
        rel = item.relative_to(ROOT)
        files.append(str(rel) + ("/" if item.is_dir() else ""))
        if len(files) >= 300:
            files.append("… (300件で省略)")
            break
    return "\n".join(files) or "ファイルはありません。"


def read_file(path: str) -> str:
    target = safe_path(path)
    if not target.is_file():
        return f"ファイルがありません: {path}"
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"テキストファイルではありません: {path}"
    if len(text) > MAX_READ:
        return text[:MAX_READ] + f"\n… ({len(text) - MAX_READ}文字を省略)"
    return text


def search_code(query: str) -> str:
    result = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in DEFAULT_IGNORES for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if query.lower() in line.lower():
                result.append(f"{path.relative_to(ROOT)}:{number}: {line[:240]}")
                if len(result) >= 100:
                    return "\n".join(result) + "\n… (100件で省略)"
    return "\n".join(result) or "該当箇所はありません。"


def run_checks() -> str:
    """Run only repository-local, read-mostly checks; no shell text is accepted."""
    commands = [[sys.executable, "-m", "compileall", "-q", "."]]
    if (ROOT / "pytest.ini").exists() or (ROOT / "tests").exists():
        commands.append([sys.executable, "-m", "pytest", "-q"])
    reports = []
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
            output = (proc.stdout + proc.stderr).strip()
            reports.append(f"$ {' '.join(command)}\n終了コード: {proc.returncode}\n{output[-4000:]}")
        except subprocess.TimeoutExpired:
            reports.append(f"$ {' '.join(command)}\nタイムアウトしました。")
    return "\n\n".join(reports)


def local_answer(task: str) -> str:
    lowered = task.lower()
    if any(word in lowered for word in ("構成", "ファイル", "一覧", "structure")):
        return "リポジトリのファイル一覧です。\n\n" + list_files()
    if any(word in lowered for word in ("テスト", "check", "compile", "動作確認")):
        return run_checks()
    if "検索" in task or "search" in lowered:
        return "検索語を指定してください。例: `python Agent.py --search GROQ_API_KEY`"
    return (
        "ローカルモードで実行しました。\n"
        "利用可能な操作: `--list`, `--read PATH`, `--search QUERY`, `--check`。\n"
        "GROQ_API_KEYを設定すると、質問をツール実行型エージェントとして処理できます。"
    )


def groq_answer(task: str, max_turns: int) -> str | None:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    try:
        from groq import Groq
    except ImportError:
        return None
    tools = [
        {"type": "function", "function": {"name": "list_files", "description": "リポジトリのファイル一覧を取得", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
        {"type": "function", "function": {"name": "read_file", "description": "リポジトリ内のテキストファイルを読む", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "search_code", "description": "リポジトリ内を文字列検索", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "run_checks", "description": "Python構文チェックと存在するテストを実行", "parameters": {"type": "object", "properties": {}}}},
    ]
    funcs = {"list_files": list_files, "read_file": read_file, "search_code": search_code, "run_checks": run_checks}
    messages: list[dict[str, Any]] = [{"role": "system", "content": "あなたは安全なローカル開発エージェントです。まず必要なら計画を短く示し、提供された読み取り・検査ツールだけを使い、推測せず日本語で結果を要約してください。ファイル変更や外部送信は行わないでください。"}, {"role": "user", "content": task}]
    client = Groq(api_key=key)
    for _ in range(max_turns):
        response = client.chat.completions.create(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), messages=messages, tools=tools, tool_choice="auto")
        message = response.choices[0].message
        messages.append(message.model_dump() if hasattr(message, "model_dump") else {"role": "assistant", "content": message.content, "tool_calls": message.tool_calls})
        if not message.tool_calls:
            return message.content or "タスクが完了しました。"
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                result = funcs[name](**args)
            except Exception as exc:
                result = f"ツール実行エラー: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.id, "name": name, "content": result})
    return "最大ターン数に達したため停止しました。取得済み情報を確認してください。"


def main() -> int:
    parser = argparse.ArgumentParser(description="安全なローカル開発エージェント")
    parser.add_argument("task", nargs="?", help="エージェントへの依頼")
    parser.add_argument("--interactive", action="store_true", help="対話モード")
    parser.add_argument("--list", action="store_true", help="ファイル一覧")
    parser.add_argument("--read", metavar="PATH", help="ファイルを表示")
    parser.add_argument("--search", metavar="QUERY", help="コードを検索")
    parser.add_argument("--check", action="store_true", help="構文・テストを確認")
    parser.add_argument("--max-turns", type=int, default=30, choices=range(1, 31))
    args = parser.parse_args()
    if args.list:
        print(list_files()); return 0
    if args.read:
        print(read_file(args.read)); return 0
    if args.search:
        print(search_code(args.search)); return 0
    if args.check:
        print(run_checks()); return 0
    if args.interactive:
        print("Agent対話モード。終了するには `exit` または Ctrl-D。")
        while True:
            try: task = input("\nYou> ").strip()
            except EOFError: break
            if task.lower() in {"exit", "quit", "終了"}: break
            if task: print("\nAgent> " + (groq_answer(task, args.max_turns) or local_answer(task)))
        return 0
    if not args.task:
        parser.print_help(); return 0
    print(groq_answer(args.task, args.max_turns) or local_answer(args.task))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
