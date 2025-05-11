import os
from datetime import datetime
import sys

def read_log(log_file_path: str) -> str:
    """指定されたログファイルの内容を読み込む．"""
    if not os.path.exists(log_file_path):
        return ""
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' の読み込み中にエラーが発生: {e}", file=sys.stderr)
        return ""

def append_to_log(log_file_path: str, entry: str):
    """指定されたログファイルにエントリを追記する．"""
    try:
        log_dir = os.path.dirname(log_file_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_entry = f"\n---\n\n**[{timestamp}]**\n\n{entry.strip()}\n"

        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(formatted_entry)
    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' への追記中にエラーが発生: {e}", file=sys.stderr)


def get_last_log_entry(log_file_path: str) -> str:
    """
    指定されたログファイルの最後のログエントリの内容だけを抽出して文字列で返す．
    タイムスタンプヘッダーを除いた純粋なエントリ内容を取得する．
    """
    content = read_log(log_file_path)
    if not content:
        return ""

    parts = content.strip().rsplit("\n---\n", 1)
    if not parts:
        return ""

    last_block = parts[-1]

    header_end_marker = "\n\n"
    marker_pos = last_block.find(header_end_marker)

    if marker_pos != -1:
        entry_content = last_block[marker_pos + len(header_end_marker):].strip()
        return entry_content
    else:
        return last_block.strip()