import bootstrap_path # インポートするだけでOK
import sys
import workflow_log_utils
from mcp.server.fastmcp import FastMCP
import json
from typing import List, Optional
print(f"DEBUG: {__file__} が引数 {sys.argv} で開始されました．", file=sys.stderr)

# Orchestrator から渡されるワークフロー固有のログファイルパスを読み込む
# sys.argv[0] はスクリプト自身のパスなので，argv[1]以降を期待する
WORKFLOW_LOG_FILE = None
if len(sys.argv) > 1:
    WORKFLOW_LOG_FILE = sys.argv[1]

if WORKFLOW_LOG_FILE is None:
    print("エラー: ワークフローログファイルパスが logging_mcp.py に指定されていません．", file=sys.stderr)

mcp = FastMCP(name="Logging and Reply Tools")

@mcp.tool()
def add_goal(goal_description: str) -> str:
    """
    ユーザーの要求に対する全体の達成基準をログに追記します．
    ユーザーの要求を分析し，必要なものや満たすべき条件を記述してください．
    このツールが呼ばれると，ワークフローは作業ステップに移行します．

    Args:
        goal_description (str): 設定する目標の詳細．

    Returns:
        str: Orchestrator にログ記録を指示するための確認メッセージ．

    Example:
        >>> add_goal("ユーザーの質問「MCPとは何か」に答えるために，まず検索ツールで情報を収集する．\n収集した情報を作業ディレクトリのmcp_info.txtに保存する．")
        '__GOAL_SET__'
    """
    if WORKFLOW_LOG_FILE:
        workflow_log_utils.append_to_log(WORKFLOW_LOG_FILE, f"## GOAL: \n{goal_description}")
        workflow_log_utils.append_to_log(WORKFLOW_LOG_FILE, "__GOAL_SET__") # シグナルもログに記録
    else:
        print("エラー: add_goal ツール実行時にWORKFLOW_LOG_FILEが設定されていません．", file=sys.stderr)
        pass

    return '__GOAL_SET__'

@mcp.tool()
def workflow_complete(message: str = "") -> str:
    """
    ワークフロー全体が完了したことを示します．
    最終目標が達成されたと判断した場合に呼び出し，
    ユーザーの要求に対する最終的な成果物（ファイルパスやリンク，知識等）を提出してください．
    達成しきれていない場合は不要です．
    このツールが呼ばれると，ワークフローはユーザーレビューまたは終了に移行します．

    Args:
        message (str, optional): ワークフロー完了の簡単なメッセージや成果物への言及．

    Returns:
        str: "__WORKFLOW_COMPLETE__" シグナル．

    Example:
        >>> workflow_complete("MCPに関する情報の収集と保存が完了しました．結果は project_workspace/workflow_<id>/mcp_info.txt を参照してください．")
        '__WORKFLOW_COMPLETE__'
    """
    append_message_log = "__WORKFLOW_COMPLETE__"
    if message:
        append_message_log += f"\nCompletion Message: {message}"

    if WORKFLOW_LOG_FILE:
        workflow_log_utils.append_to_log(WORKFLOW_LOG_FILE, append_message_log)
    else:
        print("エラー: workflow_complete ツール実行時にWORKFLOW_LOG_FILEが設定されていません．", file=sys.stderr)
        pass
    return '__WORKFLOW_COMPLETE__'


@mcp.tool()
def make_reply(reply_text: str, output_file: Optional[str] = None) -> str:
    """
    ユーザーへの最終的な返信メッセージと成果物ファイル（一つだけ，オプション）を準備します．
    このツールは，エージェントがタスクを完了し，結果を提示する準備ができたときに呼び出されるべきです．
    オーケストレーター(main.py)はこの情報を使用して最終的な応答を組み立てます．

    Args:
        reply_text (str): ユーザーに送信する返信のテキスト部分．
        output_file (str | None, optional): 添付する成果物ファイルへのパス（ワークスペースからの相対パス）．
                                            ファイルが一つもない場合は None を渡してください．

    Returns:
        str: 'reply_text' と 'output_files' を含むJSON文字列．
            'output_files' は常にリスト形式で，output_file が指定されていればそのパスを含むリスト，
            そうでなければ空リストになります．
            例: '{"reply_text": "検索結果です．", "output_files": ["result.txt"]}' または '{"reply_text": "作業完了しました．", "output_files": []}'
    """
    output_files_list = []
    if output_file is not None:
        output_files_list.append(output_file)

    payload = {
        "reply_text": reply_text,
        "output_files": output_files_list
    }
    # main.py がこのJSON文字列を ToolMessage.content として受け取る
    return json.dumps(payload)

if __name__ == '__main__':
    print(f"Logging MCP (logging_mcp.py) 開始．LOG_FILE: {WORKFLOW_LOG_FILE}", file=sys.stderr)
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        print(f"Logging MCP ランタイムエラー: {e}", file=sys.stderr)
        sys.exit(1)