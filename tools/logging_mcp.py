import bootstrap_path # インポートするだけでOK
import sys
from mcp.server.fastmcp import FastMCP
import json
from typing import List, Optional # List をインポート
print(f"DEBUG: {__file__} が引数 {sys.argv} で開始されました．", file=sys.stderr)

mcp = FastMCP(name="Logging and Reply Tools")

@mcp.tool()
def make_reply(reply_text: str, output_files: Optional[List[str]] = None) -> str:
    """
    ユーザーへの最終的な返信メッセージと成果物ファイルのリスト（オプション）を準備します．
    このツールは，エージェントがタスクを完了し，結果を提示する準備ができたときに呼び出されるべきです．
    オーケストレーター(main.py)はこの情報を使用して最終的な応答を組み立てます．

    Args:
        reply_text (str): ユーザーに送信する返信のテキスト部分．
        output_files (Optional[List[str]], optional): 添付する成果物ファイルのパスのリスト（ワークスペースからの相対パス）．
                                                    ファイルがない場合は None または空リストを渡してください．

    Returns:
        str: 'reply_text' と 'output_files' を含むJSON文字列．
             'output_files' は常にリスト形式です．
             例: '{"reply_text": "検索結果です．", "output_files": ["result.txt", "notes.md"]}'
                 '{"reply_text": "作業完了しました．", "output_files": []}'
    """
    output_files_list = []
    if output_files: # None や空リストでない場合
        if isinstance(output_files, list):
            output_files_list = [f for f in output_files if isinstance(f, str) and f]
        elif isinstance(output_files, str) and output_files:
            print("Warning: make_reply の output_files に文字列が渡されました。リストを期待しています。", file=sys.stderr)
            output_files_list = [output_files]
        else:
            print(f"Warning: make_reply の output_files が予期しない型です: {type(output_files)}", file=sys.stderr)


    payload = {
        "reply_text": reply_text,
        "output_files": output_files_list
    }
    return json.dumps(payload)

if __name__ == '__main__':
    print(f"Logging MCP (logging_mcp.py) 開始．", file=sys.stderr)
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        print(f"Logging MCP ランタイムエラー: {e}", file=sys.stderr)
        sys.exit(1)
