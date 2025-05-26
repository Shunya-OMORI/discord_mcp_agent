import bootstrap_path #インポートするだけでOK
import sys
import os
# import subprocess # execute_python_script を削除したため不要に
from mcp.server.fastmcp import FastMCP
import base64
print(f"DEBUG: {__file__} が引数 {sys.argv} で開始されました．", file=sys.stderr)

WORKFLOW_WORKSPACE = None
# WORKFLOW_LOG_FILE = None # .mdログファイルパスは使わない

if len(sys.argv) > 1:
    WORKFLOW_WORKSPACE = sys.argv[1]
# if len(sys.argv) > 2: # ログファイルパスの引数は削除
#     WORKFLOW_LOG_FILE = sys.argv[2]

if WORKFLOW_WORKSPACE is None:
    print("エラー: ワークフロー作業ディレクトリパスが指定されていません．", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP(name="FileSystem Tools")

def _safe_path(user_path: str) -> str:
    base_path = os.path.abspath(os.path.normpath(WORKFLOW_WORKSPACE))
    joined_path = os.path.abspath(os.path.normpath(os.path.join(base_path, user_path)))
    if not os.path.commonpath([joined_path, base_path]) == base_path:
        raise ValueError(f"'{user_path}' は作業ディレクトリ '{WORKFLOW_WORKSPACE}' の外を指しています．")
    return joined_path

@mcp.tool()
def create_folder(path: str) -> str:
    try:
        safe_path = _safe_path(path)
        os.makedirs(safe_path, exist_ok=True)
        return f"フォルダ '{path}' を作成しました．"
    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:
        return f"フォルダ作成中にエラーが発生しました: {e}"

@mcp.tool()
def list_folder(path: str = ".") -> str:
    try:
        safe_path = _safe_path(path)
        if not os.path.isdir(safe_path):
            return f"エラー: '{path}' はフォルダではありません．"
        contents = os.listdir(safe_path)
        if not contents:
            return f"フォルダ '{path}' は空です．"
        detailed_contents = []
        for item in contents:
            item_path = os.path.join(safe_path, item)
            if os.path.isdir(item_path):
                detailed_contents.append(f"{item}/")
            else:
                detailed_contents.append(item)
        return f"フォルダ '{path}' の内容:\n" + "\n".join(detailed_contents)
    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:
        return f"フォルダリスト表示中にエラーが発生しました: {e}"

@mcp.tool()
def read_file(path: str) -> str:
    try:
        safe_path = _safe_path(path)
        if not os.path.isfile(safe_path):
            return f"エラー: ファイル '{path}' が見つからないか，ファイルではありません．"
        
        # ファイルサイズの制限は維持
        max_size_bytes = 1 * 1024 * 1024 # 1MB
        file_size = os.path.getsize(safe_path)
        if file_size > max_size_bytes:
            return f"エラー: ファイルサイズが上限 ({max_size_bytes // (1024*1024)}MB) を超えています ({file_size} bytes)．"

        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f: # errors='replace' を追加
            content = f.read()

        return f"ファイル '{path}' の内容 (サイズ: {file_size} bytes):\n{content}"


    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:
        return f"ファイル読み取り中にエラーが発生しました: {e}"

@mcp.tool()
def write_file(path: str, content: str) -> str:
    try:
        safe_path = _safe_path(path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True) # 親ディレクトリも作成

        max_content_bytes = 1 * 1024 * 1024 # 1MB
        if len(content.encode('utf-8')) > max_content_bytes:
            return f"エラー: 書き込みコンテンツサイズが上限 ({max_content_bytes // (1024*1024)}MB) を超えています．"

        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"ファイル '{path}' に書き込みました．"
    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:
        return f"ファイル書き込み中にエラーが発生しました: {e}"

@mcp.tool()
def read_binary_file(path: str) -> dict:
    try:
        safe_path = _safe_path(path)
        if not os.path.isfile(safe_path):
            return {"error": f"ファイル '{path}' が見つからないか，ファイルではありません．"}

        max_size_bytes = 10 * 1024 * 1024 
        file_size = os.path.getsize(safe_path)
        if file_size > max_size_bytes:
            return {"error": f"ファイルサイズが上限 ({max_size_bytes // (1024*1024)}MB) を超えています ({file_size} bytes)．"}

        with open(safe_path, 'rb') as f:
            binary_content = f.read()

        encoded_content = base64.b64encode(binary_content).decode('utf-8')
        return {"filename": os.path.basename(safe_path), "content_base64": encoded_content, "size": len(binary_content)}
    except ValueError as e:
        return {"error": f"エラー: {e}"}
    except Exception as e:
        return {"error": f"バイナリファイル読み取り中にエラーが発生しました: {e}"}

@mcp.tool()
def write_binary_file(path: str, content_base64: str) -> str:
    try:
        safe_path = _safe_path(path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)

        try:
            binary_content = base64.b64decode(content_base64.encode('utf-8'), validate=True)
        except (TypeError, ValueError, base64.binascii.Error) as e: # binascii.Errorもキャッチ
            return f"エラー: 無効なBase64文字列です: {e}"

        max_size_bytes = 10 * 1024 * 1024
        if len(binary_content) > max_size_bytes:
            return f"エラー: デコード後のコンテンツサイズが上限 ({max_size_bytes // (1024*1024)}MB) を超えています．"

        with open(safe_path, 'wb') as f:
            f.write(binary_content)
        return f"バイナリファイル '{path}' に書き込みました ({len(binary_content)} bytes)."
    except ValueError as e:
        return f"エラー: {e}" 
    except Exception as e:
        return f"バイナリファイル書き込み中に予期せぬエラーが発生しました: {e}"

if __name__ == '__main__':
    # print(f"FileSystem MCP started with WORKFLOW_WORKSPACE: {WORKFLOW_WORKSPACE}, LOG_FILE (not used): {WORKFLOW_LOG_FILE}", file=sys.stderr)
    print(f"FileSystem MCP (file_system_mcp.py) 開始．WORKFLOW_WORKSPACE: {WORKFLOW_WORKSPACE}", file=sys.stderr)
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        print(f"FileSystem MCP ランタイムエラー: {e}", file=sys.stderr)
        sys.exit(1)
