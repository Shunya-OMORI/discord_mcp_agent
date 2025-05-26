import os
import json
import logging
from typing import Dict, Any, List, Tuple

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)
RESEARCH_NOTES_FILENAME = "research_notes.md"

def generate_llm_context_and_prompt(
    workflow_log_content: str,
    file_manifest: Dict[str, Any],
    workflow_workspace_path: str,
    original_initial_request: str,
    current_phase: str,
    initial_message_for_phase: str = "", 
    user_feedback: str = "" 
) -> Tuple[List[SystemMessage | HumanMessage], str]:
    """LLMに渡すメッセージリストと、ロギング用の人間向けメッセージ内容を生成する"""

    manifest_summary_for_llm = f"現在のワークスペースのファイル状況（file_manifest.json より抜粋）:\n"
    manifest_files_summary = []
    research_notes_exists = RESEARCH_NOTES_FILENAME in file_manifest.get("files", {})
    python_script_execution_errors = [] 

    for rel_path, details in file_manifest.get("files", {}).items():
        summary_item = f"- {rel_path} (type: {details.get('type', 'N/A')}, status: {details.get('status', 'N/A')}"
        if details.get('type') == 'python':
            if details.get('status') == 'executed_with_error' and details.get('execution_result'):
                summary_item += f", rc: {details['execution_result'].get('return_code', 'N/A')}"
                stderr = details['execution_result'].get('stderr', '')
                if stderr:
                    error_preview = stderr.strip().split('\n')[-1] 
                    summary_item += f", error_preview: \"{error_preview[:100]}{'...' if len(error_preview)>100 else ''}\""
                    if "ModuleNotFoundError" in stderr:
                        python_script_execution_errors.append(
                            f"  - `{rel_path}`: {error_preview} (ModuleNotFoundError)"
                        )
                    else:
                         python_script_execution_errors.append(
                            f"  - `{rel_path}`: {error_preview}"
                        )
        if details.get('type') in ['text', 'markdown_research_notes'] and 'content_char_count' in details:
            summary_item += f", chars: {details.get('content_char_count')}"
        summary_item += ")"
        manifest_files_summary.append(summary_item)
    
    if manifest_files_summary:
        manifest_summary_for_llm += "\n".join(manifest_files_summary[:20]) 
        if len(manifest_files_summary) > 20:
            manifest_summary_for_llm += "\n... (他多数のファイルあり、詳細はマニフェスト参照)"
    else:
        manifest_summary_for_llm += "(成果物ファイルはまだありません)\n"
    manifest_summary_for_llm += f"最新のマニフェスト更新時刻: {file_manifest.get('last_updated')}\n"
    
    if python_script_execution_errors:
        manifest_summary_for_llm += "**警告: 以下のPythonスクリプトで実行エラーが発生しました。内容を確認し、対処してください。**\n"
        manifest_summary_for_llm += "\n".join(python_script_execution_errors) + "\n"

    if research_notes_exists:
        manifest_summary_for_llm += f"**重要: 情報源や調査の記録は `{RESEARCH_NOTES_FILENAME}` を確認・追記してください。**\n"
    else:
        manifest_summary_for_llm += f"**情報: 調査ノート (`{RESEARCH_NOTES_FILENAME}`) はまだ作成されていません。必要に応じて作成してください。**\n"

    text_file_previews_for_llm = ""
    if current_phase == "LLM_CHECK_AND_PROCEED": 
        preview_char_limit_per_file = 500 
        total_preview_chars = 0
        max_total_preview_chars = 2000 
        for rel_path, details in file_manifest.get("files", {}).items():
            if details.get("type") in ["text", "markdown_research_notes"] and details.get("status") == "processed":
                if total_preview_chars < max_total_preview_chars:
                    try:
                        file_abs_path = os.path.join(workflow_workspace_path, rel_path)
                        if os.path.exists(file_abs_path):
                            with open(file_abs_path, "r", encoding="utf-8") as f_preview:
                                content = f_preview.read(preview_char_limit_per_file + 100) 
                            preview_content = content[:preview_char_limit_per_file]
                            is_truncated = len(content) > preview_char_limit_per_file
                            text_file_previews_for_llm += f"\n--- ファイルプレビュー: `{rel_path}` ---\n"
                            text_file_previews_for_llm += preview_content
                            if is_truncated:
                                text_file_previews_for_llm += "\n...(プレビュー省略)..."
                            text_file_previews_for_llm += f"\n--- (プレビュー終了: `{rel_path}`) ---\n"
                            total_preview_chars += len(preview_content)
                    except Exception as e_preview:
                        logger.warning(f"ファイルプレビュー読み込みエラー ({rel_path}): {e_preview}")
                else:
                    if total_preview_chars >= max_total_preview_chars: 
                        text_file_previews_for_llm += "\n...(他のファイルのプレビューは文字数上限のため省略)..."
                        break
    
    context_message_base = (
        f"現在のワークフローログ (.md):\n---\n{workflow_log_content}\n---\n" 
        f"{manifest_summary_for_llm}" 
        f"{text_file_previews_for_llm}"
        f"作業ディレクトリは '{workflow_workspace_path}' です。\n"
        f"ユーザーの最初の要求: '{original_initial_request}'\n"
    )

    if user_feedback and current_phase == "LLM_FEEDBACK_WORK": 
         context_message_base = (
            f"ユーザーからの最優先フィードバック:\n---\n{user_feedback}\n---\n"
            f"上記のフィードバックを最優先で考慮し、以下の情報も参照してください。\n"
            f"現在のワークフローログ (.md):\n---\n{workflow_log_content}\n---\n"
            f"{manifest_summary_for_llm}"
            f"{text_file_previews_for_llm}"
            f"作業ディレクトリは '{workflow_workspace_path}' です。\n"
            f"ユーザーの最初の要求: '{original_initial_request}'\n"
        )
    
    system_prompt_text = (
        "あなたは有能なAIアシスタントです。ユーザーの要求とフィードバック（あれば最優先で）を達成するために、提供されたツールを段階的に使用して作業を進めてください。"
        "ファイル操作は指示された作業ディレクトリ内で行い、結果はファイルマニフェストで確認できます。"
        f"**重要指示:** `search` ツールなどを使用して外部情報を調査した場合、その検索キーワード、参照した主要な情報源（URLとタイトルを最低でも2-3件）、およびそこから得られた重要な知見や結論を、**必ず**ワークスペース内の `{RESEARCH_NOTES_FILENAME}` というファイルにMarkdown形式で追記・更新してください。"
        f"`{RESEARCH_NOTES_FILENAME}` が存在しない場合は新規作成してください。このファイルは、成果物の根拠を示すためにユーザーに提示されることがあります。\n"
        "**Pythonスクリプトの扱い:**\n"
        "  - Pythonスクリプトの実行は自動処理フェーズで行われるため、あなたが直接実行するツールはありません。作成・編集したスクリプトは次の自動処理で実行され、結果がマニフェストに反映されます。\n"
        "  - もしPythonスクリプトの実行結果に `ModuleNotFoundError` が含まれる場合、それは必要なライブラリが実行環境にインストールされていないことを意味します。"
        "    その場合、スクリプト自体を修正してそのライブラリを使わないようにするか、それが難しい場合は、ユーザーに必要なライブラリ（例: `matplotlib`, `numpy`, `scipy`など）とそのバージョン（分かれば）を伝え、ユーザー自身が環境にインストールする必要があることを `make_reply` ツールで報告してください。エージェント自身でライブラリのインストールはできません。\n"
        "  - **グラフ等を作成するPythonスクリプトを生成する場合、日本語のタイトルやラベルが文字化けしないように、スクリプトの冒頭で `import japanize_matplotlib` を記述して `japanize_matplotlib` ライブラリを使用してください。** これにより、特別なフォント指定なしで日本語が正しく表示されるようになります。"
    )
    llm_messages: List[SystemMessage | HumanMessage] = [SystemMessage(content=system_prompt_text)]
    
    human_message_content = context_message_base 
    
    if current_phase == "LLM_INITIAL_WORK":
        human_message_content += (
            f"これはワークフローの最初の作業ステップです。ユーザーの要求と現在のファイル状況（添付ファイルなど）に基づき、"
            f"必要な作業を実行し、成果物をワークスペースにファイルとして作成してください。\n"
            f"**繰り返しになりますが、調査を行った場合は、その内容を `{RESEARCH_NOTES_FILENAME}` に必ず記録してください。**\n"
            f"このステップではユーザーへの最終返信は行いません。作業が一段落したら思考を停止してください。\n"
            f"初期指示: {initial_message_for_phase}"
        )
    elif current_phase == "LLM_FEEDBACK_WORK":
        human_message_content += ( 
            f"上記のユーザーフィードバックを最優先で考慮し、現在のファイル状況に基づき、作業を継続または修正し、成果物を更新/作成してください。\n"
            f"**繰り返しになりますが、調査を行った場合は、その内容を `{RESEARCH_NOTES_FILENAME}` に必ず記録してください。**\n"
            f"このステップではユーザーへの最終返信は行いません。作業が一段落したら思考を停止してください。"
        )
    elif current_phase == "LLM_CHECK_AND_PROCEED":
        error_handling_prompt = ""
        if python_script_execution_errors:
            error_handling_prompt = (
                "**特に、上記のPythonスクリプト実行エラーに注意してください。**\n"
                "もし `ModuleNotFoundError` が原因である場合、必要なライブラリ名を特定し、ユーザーにそのライブラリのインストールが必要である旨を `make_reply` を使って伝えてください。その際、スクリプトが画像生成を目的とする場合は、生成されるはずだった画像ファイル名も伝えると親切です。\n"
                "他の種類のエラーであれば、スクリプト (`.py` ファイル) を修正してエラー解決を試みてください。\n"
                "日本語表示のあるグラフを作成した場合は、`japanize_matplotlib` が使用されているか確認してください。\n" # 追加
            )

        human_message_content += (
            f"前のステップで自動ファイル処理が行われ、ファイルマニフェストと上記のファイルプレビューが更新されました。\n"
            f"{error_handling_prompt}" 
            f"現在のファイル状況、これまでのログ、ユーザーの初期要求（およびフィードバックがあればそれも）、そして特に `{RESEARCH_NOTES_FILENAME}` の内容を総合的に評価してください。\n"
            f"- 成果物はユーザーの要求を満たしているか？\n"
            f"- `{RESEARCH_NOTES_FILENAME}` には、成果物に至る調査の過程や根拠が十分に記録されているか？\n"
            f"- ファイル内容（Pythonの実行結果、抽出画像テキストなど）に問題はないか？エラーは解決されたか、またはユーザーに通知する必要があるか？\n"
            f"- 生成されたグラフの日本語は正しく表示されているか？（`japanize_matplotlib` の使用を確認）\n" # 追加
            f"もし作業が完了し、成果が十分であるか、またはユーザーへの報告が必要な状況（例: `ModuleNotFoundError`）であれば `make_reply` ツールでユーザーに最終報告をしてください。\n"
            f"その際、成果物ファイルは `output_files` パラメータにファイルパスのリスト（例: [\"plot_gaussian.py\", \"{RESEARCH_NOTES_FILENAME}\"]）として指定してください。ファイルがない場合は空のリスト [] を指定します。\n"
            f"まだ作業が必要な場合や修正が必要な場合は、引き続きツールを使って作業を進めてください。その場合、`make_reply` は使わないでください。"
        )
    
    llm_messages.append(HumanMessage(content=human_message_content))
    return llm_messages, human_message_content
