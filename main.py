import asyncio
import os
import json
import sys
from datetime import datetime
import logging
from typing import Dict, Any, List # List をインポート

# .env ファイルから環境変数を読み込む
from dotenv import load_dotenv, find_dotenv
_ = load_dotenv(find_dotenv())

# Langchain, MCP, Google Generative AI のインポート
from langchain_core.messages import ToolMessage # SystemMessage, HumanMessage は llm_utils へ
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient, StdioConnection
from langgraph.prebuilt import create_react_agent

# プロジェクト固有の設定とユーティリティのインポート
from config import (
    MCP_CONNECTIONS, LLM_MODEL # BASE_DIR系は workflow_setup_utils へ
)
from workflow_log_utils import read_log # append_to_log は workflow_setup_utils へ
# 分割したモジュールをインポート
from file_manifest_utils import load_file_manifest, save_file_manifest
from automatic_processing_utils import run_automatic_file_processing
from llm_utils import generate_llm_context_and_prompt
from workflow_setup_utils import setup_new_workflow, setup_existing_workflow


# --- グローバル定数 ---
FILE_MANIFEST_NAME = "file_manifest.json" # 各ユーティリティファイルでも参照するため、ここで一元管理も検討
RESEARCH_NOTES_FILENAME = "research_notes.md"
DISCORD_MESSAGE_LIMIT = 1800

# ロギング設定 (メインスクリプト用)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

async def run_workflow(
    initial_message: str,
    attachments: list[str] | None = None,
    existing_workflow_id: str | None = None,
    user_feedback_for_continuation: str | None = None
):
    workflow_id: str
    workflow_workspace_path: str
    workflow_log_file_path: str
    file_manifest: Dict[str, Any]
    original_initial_message_for_log: str
    current_user_feedback: str | None = user_feedback_for_continuation

    is_continuation = existing_workflow_id is not None

    try:
        if is_continuation:
            workflow_id, workflow_workspace_path, workflow_log_file_path, file_manifest, \
            original_initial_message_for_log, current_user_feedback = setup_existing_workflow(
                existing_workflow_id, initial_message, attachments, user_feedback_for_continuation
            )
        else:
            workflow_id, workflow_workspace_path, workflow_log_file_path, file_manifest, \
            original_initial_message_for_log = setup_new_workflow(
                initial_message, attachments
            )
    except FileNotFoundError as e_setup: # setup_existing_workflow からの例外
        logger.error(e_setup)
        return {"status": "error", "reply_text": str(e_setup), "output_files": [], "workflow_id": existing_workflow_id, "final_workspace_path": None, "log_file_path": None, "file_manifest_path": None}


    logger.info("ワークフロー開始前の初期自動ファイル処理を実行します...")
    file_manifest, _ = await run_automatic_file_processing(
        workflow_workspace_path, file_manifest
    )
    save_file_manifest(workflow_workspace_path, file_manifest)
    logger.info("初期自動ファイル処理完了。")

    logger.info("--- MCPサーバーへの接続準備中 ---")
    client_connections = {}
    for server_name, conn_config in MCP_CONNECTIONS.items():
        tool_script_path = conn_config["args"][0]
        tool_specific_args = conn_config["args"][1:]
        current_tool_args_for_mcp = [tool_script_path] + tool_specific_args
        if server_name == "filesystem":
            current_tool_args_for_mcp.append(workflow_workspace_path)
        
        if not os.path.exists(tool_script_path):
            logger.error(f"MCPツールスクリプトが見つかりません: {tool_script_path} (サーバー: {server_name})")
            return {"status": "error", "reply_text": f"設定エラー: ツールスクリプト {os.path.basename(tool_script_path)} が見つかりません．", "output_files": [], "workflow_id": workflow_id, "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path, "file_manifest_path": os.path.join(workflow_workspace_path, FILE_MANIFEST_NAME) if workflow_workspace_path else None }

        client_connections[server_name] = StdioConnection(
            command=conn_config["command"],
            args=current_tool_args_for_mcp
        )

    async with MultiServerMCPClient(client_connections) as mcp_client_instance:
        logger.info("--- MCPクライアント接続完了，サーバー起動 ---")
        try:
            gemini_llm = ChatGoogleGenerativeAI(model=LLM_MODEL)
        except Exception as e:
            logger.critical(f"LLMの初期化に失敗しました: {e}", exc_info=True)
            return {"status": "critical_error", "reply_text": "致命的なエラー: LLMを初期化できませんでした．", "output_files": [], "workflow_id": workflow_id, "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path, "file_manifest_path": os.path.join(workflow_workspace_path, FILE_MANIFEST_NAME) if workflow_workspace_path else None}

        logger.info(f"--- ワークフロー '{workflow_id}' 実行開始 ---")
        max_iterations = 15 # 1サイクルが LLM -> 自動処理 なので、実質的なLLM呼び出し回数はこの半分程度
        iteration_count = 0
        
        current_workflow_phase = "LLM_INITIAL_WORK"
        if is_continuation and current_user_feedback: # user_feedback_for_continuation を current_user_feedback に変更
            current_workflow_phase = "LLM_FEEDBACK_WORK" 
        elif is_continuation: # フィードバックなしの継続
            current_workflow_phase = "LLM_CHECK_AND_PROCEED"

        # SyntaxError修正のため、whileループをtryブロックで囲む
        try:
            while iteration_count < max_iterations:
                iteration_count += 1
                logger.info(f"\n--- ワークフロー '{workflow_id}' - イテレーション: {iteration_count}, フェーズ: {current_workflow_phase} ---")
                
                log_content_for_llm = read_log(workflow_log_file_path) 
                file_manifest = load_file_manifest(workflow_workspace_path) 
                
                llm_messages, human_message_content_for_log = generate_llm_context_and_prompt(
                    log_content_for_llm,
                    file_manifest,
                    workflow_workspace_path,
                    original_initial_message_for_log,
                    current_workflow_phase,
                    initial_message_for_phase=initial_message if current_workflow_phase == "LLM_INITIAL_WORK" else "",
                    user_feedback=current_user_feedback if current_workflow_phase == "LLM_FEEDBACK_WORK" else ""
                )
                logger.debug(f"LLMへのHumanMessage (先頭500文字):\n{human_message_content_for_log[:500]}")


                available_tools_full = mcp_client_instance.get_tools()
                tools_for_llm = available_tools_full
                
                if current_workflow_phase in ["LLM_INITIAL_WORK", "LLM_FEEDBACK_WORK"]:
                    tools_for_llm = [tool for tool in available_tools_full if tool.name != "make_reply"]
                    if not tools_for_llm: tools_for_llm = available_tools_full # 念のため
                    
                    current_llm_agent = create_react_agent(gemini_llm, tools_for_llm)
                    response = await current_llm_agent.ainvoke({"messages": llm_messages})
                    current_workflow_phase = "AUTOMATIC_FILE_PROCESSING"

                elif current_workflow_phase == "AUTOMATIC_FILE_PROCESSING":
                    file_manifest, manifest_updated = await run_automatic_file_processing(
                        workflow_workspace_path, file_manifest
                    )
                    save_file_manifest(workflow_workspace_path, file_manifest)
                    current_workflow_phase = "LLM_CHECK_AND_PROCEED"
                    # このフェーズではLLM呼び出しはないので、ループの先頭に戻る
                    if iteration_count >= max_iterations: # 自動処理後に最大反復に達した場合
                        logger.warning(f"自動処理後、最大反復回数 ({max_iterations}) に到達。")
                        # この場合、次のLLM_CHECK_AND_PROCEEDは実行されないので、ここで終了処理。
                        # ただし、通常はLLMの応答後に最大反復チェックが入る。
                        # ここでは、ループ条件で判定されるので、特別な処理は不要。
                    continue 

                elif current_workflow_phase == "LLM_CHECK_AND_PROCEED":
                    current_llm_agent = create_react_agent(gemini_llm, available_tools_full) # 全ツール利用可能
                    response = await current_llm_agent.ainvoke({"messages": llm_messages})
                    # 次のデフォルトフェーズは自動処理。make_replyが呼ばれればループを抜ける。
                    current_workflow_phase = "AUTOMATIC_FILE_PROCESSING" 
                else: 
                    logger.error(f"未定義のワークフローフェーズ: {current_workflow_phase}")
                    # このエラーはループ内で発生するので、ループを抜けてエラーリターン
                    raise ValueError(f"内部エラー: 未定義のワークフローフェーズ {current_workflow_phase}")


                detected_signals = []
                final_reply_text_from_tool = "" 
                final_output_files_from_tool: List[str] = [] 
                
                if response and response.get("messages"):
                    for resp_msg in response["messages"]:
                        if isinstance(resp_msg, ToolMessage):
                            tool_output_content = str(resp_msg.content)
                            tool_name_called = resp_msg.name
                            logger.info(f"--- ツール実行: {tool_name_called}, 出力(先頭100文字): {tool_output_content[:100]} ---")

                            if tool_name_called == "make_reply":
                                detected_signals.append("__REPLY_GENERATED__")
                                try:
                                    payload = json.loads(tool_output_content)
                                    final_reply_text_from_tool = payload.get("reply_text", "エラー: ツールから返信テキストが欠落しています．")
                                    output_files_relative = payload.get("output_files", [])
                                    if not isinstance(output_files_relative, list):
                                        logger.warning(f"make_reply の output_files がリストではありません: {output_files_relative}")
                                        output_files_relative = [str(output_files_relative)] if output_files_relative else []
                                    final_output_files_from_tool = [os.path.join(workflow_workspace_path, f.lstrip('./\\')) for f in output_files_relative if f]
                                except json.JSONDecodeError as e:
                                    logger.error(f"make_replyからのJSONパース失敗: {e}．内容: {tool_output_content}")
                                    final_reply_text_from_tool = f"エラー: エージェントからの返信内容を処理できませんでした (JSONエラー)。"
                
                if "__REPLY_GENERATED__" in detected_signals:
                    logger.info("--- 返信生成完了。ワークフローを終了します。 ---")
                    
                    processed_reply_text = final_reply_text_from_tool
                    
                    research_notes_abs_path = os.path.join(workflow_workspace_path, RESEARCH_NOTES_FILENAME)
                    if os.path.exists(research_notes_abs_path) and research_notes_abs_path not in final_output_files_from_tool:
                        logger.info(f"調査ノート {RESEARCH_NOTES_FILENAME} を成果物リストに追加します。")
                        final_output_files_from_tool.append(research_notes_abs_path)

                    for output_file_path in final_output_files_from_tool:
                        if os.path.isfile(output_file_path) and \
                           (output_file_path.lower().endswith(".txt") or output_file_path.lower().endswith(".md")):
                            try:
                                with open(output_file_path, "r", encoding="utf-8") as f_content:
                                    content = f_content.read()
                                if len(processed_reply_text) + len(content) + 100 < DISCORD_MESSAGE_LIMIT: 
                                    processed_reply_text += f"\n\n--- 添付ファイル `{os.path.basename(output_file_path)}` の内容 ---\n{content}"
                                    logger.info(f"ファイル '{os.path.basename(output_file_path)}' の内容を返信テキストに含めました。")
                                    break 
                            except Exception as e_read_final:
                                logger.warning(f"最終返信のためのファイル読み込みエラー ({output_file_path}): {e_read_final}")
                    
                    save_file_manifest(workflow_workspace_path, file_manifest)
                    return {
                        "status": "success", "reply_text": processed_reply_text,
                        "output_files": final_output_files_from_tool, "workflow_id": workflow_id,
                        "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path,
                        "file_manifest_path": os.path.join(workflow_workspace_path, FILE_MANIFEST_NAME)
                    }
            
            # while ループの最後 (最大反復回数到達時)
            logger.warning(f"ワークフロー '{workflow_id}' が最大繰り返し回数 ({max_iterations}) に達しました．")
            save_file_manifest(workflow_workspace_path, file_manifest)
            return {
                "status": "max_iterations_reached",
                "reply_text": "ワークフローが最大繰り返し回数に達しました．詳細はファイルマニフェストを確認してください．",
                "output_files": [], "workflow_id": workflow_id,
                "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path,
                "file_manifest_path": os.path.join(workflow_workspace_path, FILE_MANIFEST_NAME)
            }

        except Exception as e_main_loop: # ここが SyntaxError のあった箇所に対応
            logger.critical(f"ワークフロー '{workflow_id}' のメインループで予期せぬエラー: {e_main_loop}", exc_info=True)
            if workflow_workspace_path and os.path.exists(workflow_workspace_path) and file_manifest: # file_manifestが定義されているか確認
                save_file_manifest(workflow_workspace_path, file_manifest)
            return {
                "status": "error", "reply_text": f"ワークフロー実行中に致命的なエラーが発生しました: {e_main_loop}", 
                "output_files": [], "workflow_id": workflow_id, 
                "final_workspace_path": workflow_workspace_path, 
                "log_file_path": workflow_log_file_path,
                "file_manifest_path": os.path.join(workflow_workspace_path, FILE_MANIFEST_NAME) if workflow_workspace_path else None
            }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stdout)
    logger.info("main.py をテスト目的で直接実行します．")

    # config は main.py と同じ階層にある想定
    from config import ensure_directories, check_tool_scripts
    ensure_directories()
    if not check_tool_scripts():
        logger.critical("一部のMCPツールスクリプトが見つからないため，テストを中止します．")
        sys.exit(1)

    current_workflow_id_for_test = None
    while True:
        attachments_for_test: List[str] = [] # 型ヒント追加
        # (テスト用一時ファイル作成のコードは省略)

        if current_workflow_id_for_test:
            user_query_for_test = input(f"ワークフロー {current_workflow_id_for_test} に追加で指示/フィードバックを入力 ('終了'で終了, '新規'で新規開始):\n> ")
            if user_query_for_test.lower() == '終了': break
            if user_query_for_test.lower() == '新規':
                current_workflow_id_for_test = None
                continue
            
            result_for_test = asyncio.run(run_workflow(
                initial_message="継続時のダミーメッセージ",
                attachments=attachments_for_test,
                existing_workflow_id=current_workflow_id_for_test,
                user_feedback_for_continuation=user_query_for_test
            ))
        else:
            user_query_for_test = input("実行したいタスクを入力してください（'終了'で終了）:\n> ")
            if user_query_for_test.lower() == '終了': break
            if not user_query_for_test: continue
            
            result_for_test = asyncio.run(run_workflow(
                initial_message=user_query_for_test,
                attachments=attachments_for_test
            ))

        logger.info(f"\n--- ワークフローテスト結果 ---")
        logger.info(f"ステータス: {result_for_test.get('status')}")
        logger.info(f"返信テキスト:\n{result_for_test.get('reply_text')}")
        logger.info(f"出力ファイル: {result_for_test.get('output_files')}")
        logger.info(f"ワークフローID: {result_for_test.get('workflow_id')}")
        logger.info(f"ワークスペースパス: {result_for_test.get('final_workspace_path')}")
        logger.info(f"ログファイルパス: {result_for_test.get('log_file_path')}")
        logger.info(f"ファイルマニフェストパス: {result_for_test.get('file_manifest_path')}")

        if result_for_test.get('status') in ["success", "max_iterations_reached"] and result_for_test.get('workflow_id'):
            prompt_continue = input("このワークフローを継続しますか？ (y/N): ")
            if prompt_continue.lower() == 'y':
                current_workflow_id_for_test = result_for_test.get('workflow_id')
            else:
                current_workflow_id_for_test = None
        else:
            current_workflow_id_for_test = None
            if result_for_test.get('status') == 'error' or result_for_test.get('status') == 'critical_error':
                 logger.error("ワークフローがエラーで終了したため、継続できません。")
        
    logger.info("テスト実行を終了します．")
