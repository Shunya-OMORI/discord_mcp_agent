import bootstrap_path #インポートするだけでOK
import sys
import os
import subprocess
from mcp.server.fastmcp import FastMCP
import base64
print(f"DEBUG: {__file__} が引数 {sys.argv} で開始されました．", file=sys.stderr)

# Orchestrator から渡されるワークフロー固有の作業ディレクトリパスを読み込む
# sys.argv[0] はスクリプト自身のパスなので，argv[1]以降を期待する
WORKFLOW_WORKSPACE = None
WORKFLOW_LOG_FILE = None

if len(sys.argv) > 1:
    WORKFLOW_WORKSPACE = sys.argv[1]
if len(sys.argv) > 2:
    WORKFLOW_LOG_FILE = sys.argv[2]

if WORKFLOW_WORKSPACE is None:
    print("エラー: ワークフロー作業ディレクトリパスが指定されていません．", file=sys.stderr)
    sys.exit(1)

# FastMCP サーバーを初期化
mcp = FastMCP(name="FileSystem Tools")

def _safe_path(user_path: str) -> str:
    """
    ユーザーから提供されたパスを作業ディレクトリ内に制限するための安全なパスを生成します．
    作業ディレクトリ外へのアクセスを防ぎます．
    """
    base_path = os.path.abspath(os.path.normpath(WORKFLOW_WORKSPACE))
    joined_path = os.path.abspath(os.path.normpath(os.path.join(base_path, user_path)))

    if not os.path.commonpath([joined_path, base_path]) == base_path:
        raise ValueError(f"'{user_path}' は作業ディレクトリ '{WORKFLOW_WORKSPACE}' の外を指しています．")

    return joined_path

@mcp.tool()
def create_folder(path: str) -> str:
    """
    作業ディレクトリ内に新しいフォルダを作成します．

    Args:
        path (str): 作業ディレクトリからの相対パスまたはフォルダ名．

    Returns:
        str: 成功またはエラーメッセージ．
    """
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
    """
    作業ディレクトリ内または指定されたフォルダの内容をリスト表示します．

    Args:
        path (str, optional): リスト表示するフォルダの作業ディレクトリからの相対パス．デフォルトは '.' (作業ディレクトリ自身)．

    Returns:
        str: フォルダの内容またはエラーメッセージ．
    """
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
    """
    作業ディレクトリ内のファイルのコンテンツを読み取ります．
    巨大なファイルの場合は先頭部分のみを返します．

    Args:
        path (str): 作業ディレクトリからの相対パスまたはファイル名．

    Returns:
        str: ファイルの内容またはエラーメッセージ．
    """
    try:
        safe_path = _safe_path(path)
        if not os.path.isfile(safe_path):
            return f"エラー: ファイル '{path}' が見つからないか，ファイルではありません．"

        max_size_bytes = 1 * 1024 * 1024 # 1MB
        file_size = os.path.getsize(safe_path)
        if file_size > max_size_bytes:
            return f"エラー: ファイルサイズが上限 ({max_size_bytes} bytes) を超えています ({file_size} bytes)．read_binary_fileを使用するか，ファイルを分割してください．"

        with open(safe_path, 'r', encoding='utf-8') as f:
            content = f.read()

        preview_limit = 10000
        truncated_output = len(content) > preview_limit
        output_content = content[:preview_limit]

        response = f"ファイル '{path}' の内容:\n{output_content}{'...' if truncated_output else ''}"
        if truncated_output:
            response += f"\n(ファイルサイズ: {file_size} bytes, 表示は先頭 {preview_limit} 文字に制限)"
        else:
            response += f"\n(ファイルサイズ: {file_size} bytes)"

        return response

    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:
        return f"ファイル読み取り中にエラーが発生しました: {e}"

@mcp.tool()
def write_file(path: str, content: str) -> str:
    """
    作業ディレクトリ内にファイルを書き込みます．ファイルが存在する場合は上書きします．
    必要に応じて親フォルダを作成します．

    Args:
        path (str): 作業ディレクトリからの相対パスまたはファイル名．
        content (str): ファイルに書き込む内容．

    Returns:
        str: 成功またはエラーメッセージ．
    """
    try:
        safe_path = _safe_path(path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)

        max_content_bytes = 1 * 1024 * 1024
        if len(content.encode('utf-8')) > max_content_bytes:
            return f"エラー: 書き込みコンテンツサイズが上限 ({max_content_bytes} bytes) を超えています．"


        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"ファイル '{path}' に書き込みました．"
    except ValueError as e:
        return f"エラー: {e}"
    except Exception as e:
        return f"ファイル書き込み中にエラーが発生しました: {e}"

@mcp.tool()
def execute_python_script(script_path: str) -> str:
    """
    指定されたPythonスクリプトを作業ディレクトリ内で実行します．
    このツールは，作業ディレクトリ内の '.py' ファイルのみを実行できます．
    コマンドの標準出力と標準エラー出力をキャプチャし，結果を返します．
    スクリプトの実行が失敗した場合は，エラーメッセージを返します．

    Args:
        script_path (str): 作業ディレクトリからの相対パスまたはPythonファイル名 (.py)．

    Returns:
        str: スクリプトの標準出力，標準エラー出力，またはエラーメッセージ．

    Example:
        >>> execute_python_script("my_script.py")
        >>> execute_python_script("scripts/analysis.py")
    """
    try:
        # パスの安全性を検証
        safe_path = _safe_path(script_path)

        # 指定されたパスがファイルであるか，Pythonスクリプトであるかを検証
        if not os.path.isfile(safe_path):
            return f"エラー: '{script_path}' はファイルではありません，または見つかりません．"
        if not safe_path.lower().endswith('.py'):
            # 厳密に .py で終わるファイルのみ許可する場合
            return f"エラー: '{script_path}' はPythonスクリプト (.py 拡張子) ではありません．"
            # .py 拡張子がなくとも python コマンドで実行させたい場合は上記チェックを外す

        # 実行するコマンドを構築 (shell=False のためリスト形式)
        # sys.executable を使うことで，ツールを実行しているPython環境のインタープリタを使用
        command = [sys.executable, safe_path]

        # 作業ディレクトリ (WORKFLOW_WORKSPACE) でコマンドを実行
        result = subprocess.run(command, cwd=WORKFLOW_WORKSPACE,
                                capture_output=True, text=True, check=True, timeout=120) # タイムアウト設定 (120秒)

        output = result.stdout.strip()
        error = result.stderr.strip()
        response_parts = []

        if output:
            response_parts.append(f"スクリプト実行結果 (stdout):\n```\n{output}\n```")
        if error:
            response_parts.append(f"スクリプト実行結果 (stderr):\n```\n{error}\n```")

        if not response_parts:
            return f"スクリプト '{script_path}' は正常に実行されましたが，出力はありませんでした．"

        return "\n".join(response_parts)

    except FileNotFoundError:
        # sys.executable が見つからない，または safe_path が存在しない (これは_safe_pathとisfileで大部分防げるが念のため)
        return f"エラー: Pythonインタープリタまたはスクリプト '{script_path}' が見つかりません．"
    except ValueError as e:
        # _safe_path からのエラー
        return f"エラー: {e}"
    except subprocess.CalledProcessError as e:
        # スクリプトがゼロ以外の終了コードで終了した場合
        return f"エラー: スクリプトがゼロ以外の終了コードを返しました ({e.returncode}).\nStdout:\n```\n{e.stdout.strip()}\n```\nStderr:\n```\n{e.stderr.strip()}\n```"
    except subprocess.TimeoutExpired:
        # タイムアウトした場合
        return f"エラー: スクリプトがタイムアウトしました (120秒)．"
    except Exception as e:
        # その他の予期せぬエラー
        return f"スクリプト実行中に予期せぬエラーが発生しました: {e}"


@mcp.tool()
def read_binary_file(path: str) -> dict:
    """
    作業ディレクトリ内のバイナリファイルのコンテンツを読み取り，Base64エンコードして返します．
    戻り値は，ファイル名，Base64エンコードされたコンテンツ，ファイルサイズを含む辞書です．

    Args:
        path (str): 作業ディレクトリからの相対パスまたはファイル名．

    Returns:
        dict: 成功時はファイル情報とコンテンツを含む辞書，エラー時はエラーメッセージを含む辞書．
            例: {"filename": "image.png", "content_base64": "...", "size": 12345}
                {"error": "エラーメッセージ"}
    """
    try:
        safe_path = _safe_path(path)
        if not os.path.isfile(safe_path):
            return {"error": f"ファイル '{path}' が見つからないか，ファイルではありません．"}

        max_size_bytes = 10 * 1024 * 1024 # 例: 10MB
        file_size = os.path.getsize(safe_path)
        if file_size > max_size_bytes:
            return {"error": f"ファイルサイズが上限 ({max_size_bytes} bytes) を超えています ({file_size} bytes)．"}

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
    """
    Base64エンコードされたコンテンツを作業ディレクトリ内にバイナリファイルとして書き込みます．
    ファイルが存在する場合は上書きします．必要に応じて親フォルダを作成します．

    Args:
        path (str): 作業ディレクトリからの相対パスまたはファイル名．
        content_base64 (str): Base64エンコードされたファイル内容．

    Returns:
        str: 成功またはエラーメッセージ．
    """
    try:
        safe_path = _safe_path(path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)

        try:
            binary_content = base64.b64decode(content_base64.encode('utf-8'), validate=True) # validate=True で不正なBase64を検出
        except (TypeError, ValueError) as e:
            return f"エラー: 無効なBase64文字列です: {e}"

        max_size_bytes = 10 * 1024 * 1024
        if len(binary_content) > max_size_bytes:
            return f"エラー: デコード後のコンテンツサイズが上限 ({max_size_bytes} bytes) を超えています．"

        with open(safe_path, 'wb') as f:
            f.write(binary_content)
        return f"バイナリファイル '{path}' に書き込みました ({len(binary_content)} bytes)."
    except ValueError as e:
        return f"エラー: {e}" # _safe_pathからのValueError
    except Exception as e:
        return f"バイナリファイル書き込み中に予期せぬエラーが発生しました: {e}"

if __name__ == '__main__':
    print(f"FileSystem MCP started with WORKFLOW_WORKSPACE: {WORKFLOW_WORKSPACE}, LOG_FILE: {WORKFLOW_LOG_FILE}", file=sys.stderr) # デバッグ用
    mcp.run(transport="stdio")