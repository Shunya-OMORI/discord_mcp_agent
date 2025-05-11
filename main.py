import asyncio
import shutil
import os
import json
from datetime import datetime
import sys
import uuid
import re

from dotenv import load_dotenv, find_dotenv
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient, StdioConnection
from langgraph.prebuilt import create_react_agent

from config import (
    BASE_WORKFLOW_LOGS_DIR, BASE_PROJECT_WORKSPACE_DIR,
    MCP_CONNECTIONS, LLM_MODEL
)
from workflow_log_utils import read_log, append_to_log

import logging

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

_ = load_dotenv(find_dotenv())

async def run_workflow(
    initial_message: str,
    attachments: list[str] | None = None,
    existing_workflow_id: str | None = None,
    user_feedback_for_continuation: str | None = None
):
    """
    エージェントワークフロー全体を実行，または既存のものを継続します．
    Discordボットがユーザーに応答するために必要な情報（返信テキスト，ファイルパスなど）を含む辞書を返します．
    """
    workflow_id: str
    workflow_workspace_path: str
    workflow_log_file_path: str
    current_step: int

    original_initial_message = initial_message

    if existing_workflow_id:
        # 既存ワークフローの継続処理
        workflow_id = existing_workflow_id
        workflow_workspace_path = os.path.join(BASE_PROJECT_WORKSPACE_DIR, f"workflow_{workflow_id}")
        workflow_log_file_path = os.path.join(BASE_WORKFLOW_LOGS_DIR, f"workflow_{workflow_id}.md")

        if not os.path.exists(workflow_workspace_path) or not os.path.exists(workflow_log_file_path):
            err_msg = f"エラー: 既存ワークフローのデータ (ID: {workflow_id}) が見つかりません．"
            logger.error(err_msg)
            return {
                "status": "error", "reply_text": err_msg, "output_files": [],
                "workflow_id": workflow_id, "final_workspace_path": None, "log_file_path": None
            }
        logger.info(f"既存ワークフローを継続します: {workflow_id} (ワークスペース: {workflow_workspace_path})")

        log_content_full = read_log(workflow_log_file_path)
        original_match = re.search(r"初回ユーザーリクエスト: (.+)\n", log_content_full)
        if original_match:
            original_initial_message = original_match.group(1).strip()
            logger.debug(f"ログから初回ユーザーリクエストを読み出し: '{original_initial_message}'")
        else:
            logger.warning(f"ログファイル '{workflow_log_file_path}' から初回ユーザーリクエストを抽出できませんでした．継続時の返信生成に影響する可能性があります．")

        if user_feedback_for_continuation:
            append_to_log(workflow_log_file_path, f"## ワークフロー継続 (ユーザーより)\nユーザーフィードバック: {user_feedback_for_continuation}\n---")
            current_step = 4 # フィードバック処理ステップから再開
        else:
            append_to_log(workflow_log_file_path, f"## ワークフロー継続 (ユーザーより)\n(フィードバックなし)\n---")
            current_step = 2 # 作業実行ステップから再開
            logger.warning(f"継続ワークフロー ({workflow_id}) にフィードバックが指定されていませんでした．ステップ2から再開します．")

    else:
        # 新規ワークフローの開始処理
        workflow_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        workflow_workspace_path = os.path.join(BASE_PROJECT_WORKSPACE_DIR, f"workflow_{workflow_id}")
        workflow_log_file_path = os.path.join(BASE_WORKFLOW_LOGS_DIR, f"workflow_{workflow_id}.md")
        current_step = 1 # 目標設定ステップから開始

        os.makedirs(workflow_workspace_path, exist_ok=True)
        log_dir = os.path.dirname(workflow_log_file_path)
        os.makedirs(log_dir, exist_ok=True)

        with open(workflow_log_file_path, "w", encoding="utf-8") as f:
            f.write(f"# エージェントワークフローログ (ID: {workflow_id})\n\n")
            f.write(f"ワークフロー・ワークスペース: `{workflow_workspace_path}`\n")
            f.write(f"初回ユーザーリクエスト: {original_initial_message}\n---\n")
        logger.info(f"新規ワークフロー '{workflow_id}' を開始しました．ログ: '{workflow_log_file_path}'")

        if attachments:
            append_to_log(workflow_log_file_path, "## 受信した添付ファイル:")
            for temp_att_path in attachments:
                if os.path.exists(temp_att_path):
                    filename = os.path.basename(temp_att_path)
                    dest_path = os.path.join(workflow_workspace_path, filename)
                    try:
                        shutil.copy(temp_att_path, dest_path)
                        logger.info(f"添付ファイル '{filename}' を '{dest_path}' にコピーしました．")
                        append_to_log(workflow_log_file_path, f"- ファイル '{filename}' をワークスペースにコピーしました．")
                    except Exception as e_copy:
                        logger.error(f"添付ファイル '{filename}' のワークスペースへのコピーに失敗: {e_copy}")
                        append_to_log(workflow_log_file_path, f"- エラー: ファイル '{filename}' のコピー失敗 - {e_copy}")
                else:
                    logger.warning(f"添付ファイルのパス '{temp_att_path}' が見つかりません．")
                    append_to_log(workflow_log_file_path, f"- 警告: 添付ファイルパス '{temp_att_path}' が見つかりません．")
            append_to_log(workflow_log_file_path, "---")

    # MCPサーバーへの接続準備
    logger.info("--- MCPサーバーへの接続準備中 ---")
    client_connections = {}
    for server_name, conn_config in MCP_CONNECTIONS.items():
        tool_script_path = conn_config["args"][0]
        tool_specific_args = conn_config["args"][1:]

        current_tool_args_for_mcp = [tool_script_path] + tool_specific_args

        # ワークスペースとログパスを必要なツールに渡す
        if server_name == "filesystem":
            current_tool_args_for_mcp.append(workflow_workspace_path)
            current_tool_args_for_mcp.append(workflow_log_file_path)
        elif server_name == "logging":
            current_tool_args_for_mcp.append(workflow_log_file_path)
        elif server_name == "search":
            current_tool_args_for_mcp.append(workflow_log_file_path)

        if not os.path.exists(tool_script_path):
            logger.error(f"MCPツールスクリプトが見つかりません: {tool_script_path} (サーバー: {server_name})")
            return {
                "status": "error", "reply_text": f"設定エラー: ツールスクリプト {os.path.basename(tool_script_path)} が見つかりません．",
                "output_files": [], "workflow_id": workflow_id,
                "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path
            }

        client_connections[server_name] = StdioConnection(
            command=conn_config["command"],
            args=current_tool_args_for_mcp
        )
        logger.debug(f"StdioConnection 設定完了: {server_name} (実行: {conn_config['command']}, 引数: {current_tool_args_for_mcp})")

    async with MultiServerMCPClient(client_connections) as mcp_client_instance:
        logger.info("--- MCPクライアント接続完了，サーバー起動 ---")
        logger.info(f"--- LLM初期化中: {LLM_MODEL} ---")
        try:
            gemini = ChatGoogleGenerativeAI(model=LLM_MODEL)
        except Exception as e:
            logger.critical(f"LLMの初期化に失敗しました: {e}", exc_info=True)
            return {
                "status": "critical_error", "reply_text": "致命的なエラー: LLMを初期化できませんでした．",
                "output_files": [], "workflow_id": workflow_id,
                "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path
            }

        logger.info(f"--- ワークフロー '{workflow_id}' 実行開始 ---")

        max_iterations = 10
        iteration_count = 0

        is_continuation = existing_workflow_id is not None

        while iteration_count < max_iterations:
            iteration_count += 1
            logger.info(f"\n--- ワークフロー '{workflow_id}' - ステップ: {current_step} (繰り返し: {iteration_count}) ---")
            log_content = read_log(workflow_log_file_path)

            available_tools = mcp_client_instance.get_tools()
            tool_names = [t.name for t in available_tools]
            logger.debug(f"LLMが利用可能なツール: {tool_names}")

            if current_step == 3 and not any(tool.name == 'make_reply' for tool in available_tools):
                logger.warning("警告: ステップ3では 'make_reply' ツールが必要ですが，利用可能なツールリストに見つかりません！")

            llm = create_react_agent(gemini, available_tools)
            llm_input_messages = []

            truncated_log_context = log_content[-3000:]
            context_message = (
                f"現在の状況を把握するためのログの抜粋です:\n```markdown\n{truncated_log_context}\n```\n"
                f"現在のワークフローの作業ディレクトリは '{workflow_workspace_path}' です．ファイル操作はこのディレクトリ内で相対パスを使用して行ってください．\n"
            )

            # プロンプト生成の条件分岐
            if current_step == 1: # 目標設定ステップ (新規のみ)
                llm_input_messages.append(HumanMessage(
                    content=f"{context_message}\nユーザーからの最初の要求は以下の通りです:\n---\n{original_initial_message}\n---\n"
                            f"この要求に基づいて，最終的な達成目標を定義し，`add_goal` ツールを使ってログに '## GOAL: ' の形式で追記してください．目標は明確かつ実現可能なものにしてください．目標設定後は停止してください．"
                ))

            elif current_step == 2: # 作業実行ステップ
                llm_input_messages.append(HumanMessage(
                    content=f"{context_message}\nログに記載されている最新の GOAL に基づいて，利用可能なツールを使用して作業を進めてください．\n"
                            f"現在の作業ディレクトリは '{workflow_workspace_path}' です．ファイル操作はこのディレクトリ内で行ってください．\n"
                            f"最終目標を達成した場合は `workflow_complete` ツールを使用し，成果物（例: ファイルパス）について言及して完了を通知してください．まだ達成できていない場合は，作業を一つ進めて停止してください．"
                ))

            elif current_step == 3: # 返信生成ステップ
                feedback_ref_in_prompt = ""
                if is_continuation and user_feedback_for_continuation:
                    feedback_ref_in_prompt = f"特に，ユーザーからの最新のフィードバック「{user_feedback_for_continuation}」を考慮し，"
                    reply_instruction = (
                        f"このワークフローはユーザーからのフィードバックを受けて継続され，完了しました．ユーザーの最初の要求 ('{original_initial_message}') と，"
                        f"{feedback_ref_in_prompt}"
                        f"**フィードバックを受けて，ワークフローが最終的に何を達成したか，またはどのように課題に対応したか**を報告してください．\n"
                    )
                elif is_continuation:
                    reply_instruction = (
                        f"このワークフローは継続実行されました．ユーザーの最初の要求 ('{original_initial_message}') に対して，"
                        f"**ワークフローが何を達成したか**を報告してください．継続前の状況（ログを確認）も考慮に入れてください．\n"
                    )
                else:
                    reply_instruction = (
                        f"ワークフローが完了しました．ユーザーの最初の要求 ('{original_initial_message}') に対して，"
                        f"**ワークフローが何を達成したか**を報告してください．\n"
                    )

                llm_input_messages.append(HumanMessage(
                    content=f"{context_message}\nワークフローが完了しました．ユーザーへの最終返信を生成する必要があります．\n"
                            f"{reply_instruction}"
                            f"これまでのログ全体と，'{workflow_workspace_path}' 内に作成された成果物を総合的に考慮し，返信内容を生成してください．\n"
                            f"`make_reply` ツールを使用し，`reply_text` にユーザーへのメッセージ，`output_files` に成果物のファイルパス（ワークスペースからの相対パスのリスト）を指定して，返信内容を生成してください．返信生成後は停止してください．"
                ))

            elif current_step == 4: # フィードバック処理ステップ
                feedback_message_for_llm = ""
                if user_feedback_for_continuation:
                    feedback_message_for_llm = f"ユーザーから以下の最新フィードバック/追加の指示がありました:\n---\n{user_feedback_for_continuation}\n---\n"

                llm_input_messages.append(HumanMessage(
                    content=f"{context_message}\n"
                            f"{feedback_message_for_llm}"
                            f"このワークフローはユーザーからのフィードバックを受けて継続されています．ユーザーの最初の要求 ('{original_initial_message}') と，これまでのログ（特に設定済みのGOALや計画），および上記の最新のフィードバックをよく確認してください．\n"
                            f"**フィードバックに基づいて最終目標を再定義し，`add_goal` ツールを使用してログに新しいGOALを追記してください．目標再設定後は停止してください．\n"
                ))

            logger.debug(f"LLMへの入力メッセージ (ステップ{current_step}): {llm_input_messages[0].content[:500]}...")

            response = await llm.ainvoke({"messages": llm_input_messages})

            detected_signals = []
            final_reply_text_from_tool = None
            final_output_files_from_tool = []

            logger.info("--- LLM応答メッセージの処理中 ---")
            for msg_idx, resp_msg in enumerate(response["messages"]):
                log_entry = f"## LLM/ツールメッセージ {msg_idx+1}:\nタイプ: {type(resp_msg).__name__}\n"
                if hasattr(resp_msg, 'name') and resp_msg.name: log_entry += f"名前/ツール名: {resp_msg.name}\n"
                if hasattr(resp_msg, 'tool_call_id') and resp_msg.tool_call_id: log_entry += f"ツール呼び出しID: {resp_msg.tool_call_id}\n"

                content_to_log = ""
                if hasattr(resp_msg, 'content'):
                    content_to_log = str(resp_msg.content)
                    if isinstance(resp_msg, AIMessage) and len(content_to_log) > 1000:
                        content_to_log = content_to_log[:1000] + "... (省略)"
                    if isinstance(resp_msg, ToolMessage) and len(content_to_log) > 1000:
                        content_to_log = content_to_log[:1000] + "... (省略)"

                log_entry += f"内容: {content_to_log}\n"
                append_to_log(workflow_log_file_path, log_entry + "---")
                logger.debug(f"ログ記録メッセージ: {log_entry.splitlines()[0]}...")

                if isinstance(resp_msg, ToolMessage):
                    tool_output_content = str(resp_msg.content)
                    tool_name_called = resp_msg.name
                    logger.info(f"--- ツール実行: {tool_name_called}, 出力(先頭100文字): {tool_output_content[:100]} ---")

                    if tool_name_called == "add_goal" and tool_output_content == "__GOAL_SET__":
                        detected_signals.append("__GOAL_SET__")
                    elif tool_name_called == "workflow_complete" and tool_output_content == "__WORKFLOW_COMPLETE__":
                        detected_signals.append("__WORKFLOW_COMPLETE__")
                    elif tool_name_called == "make_reply":
                        detected_signals.append("__REPLY_GENERATED__")
                        try:
                            payload = json.loads(tool_output_content)
                            final_reply_text_from_tool = payload.get("reply_text", "エラー: ツールから返信テキストが欠落しています．")
                            final_output_files_from_tool = payload.get("output_files", [])
                            logger.info(f"make_reply ツール成功: テキスト='{final_reply_text_from_tool[:50]}...', ファイル数={len(final_output_files_from_tool)}")
                        except json.JSONDecodeError as e:
                            logger.error(f"make_replyからのJSONパース失敗: {e}．内容: {tool_output_content}")
                            final_reply_text_from_tool = f"エラー: エージェントからの返信内容を処理できませんでした (JSONエラー: {e})．"
                        except Exception as e_payload:
                            logger.error(f"make_replyのペイロード処理中エラー: {e_payload}．内容: {tool_output_content}")
                            final_reply_text_from_tool = f"エラー: エージェントからの返信内容を解釈できませんでした (処理エラー: {e_payload})．"

            logger.info(f"--- 検出されたシグナル: {detected_signals} ---")
            state_transitioned_this_iteration = False

            # 状態遷移ロジック
            if current_step == 1: # 目標設定ステップ
                if "__GOAL_SET__" in detected_signals:
                    current_step = 2
                    append_to_log(workflow_log_file_path, "システム: 目標設定完了．作業実行ステップに移行します．\n---")
                    logger.info("--- ステップ2へ移行: 作業実行 ---")
                    state_transitioned_this_iteration = True
                else:
                    logger.warning(f"ステップ1: __GOAL_SET__ シグナルが検出されませんでした．LLMへの指示が不明確か，ツールが失敗した可能性があります．")
                    append_to_log(workflow_log_file_path, "システム警告: 目標が設定されませんでした．LLMの思考を確認してください．\n---")

            elif current_step == 2: # 作業実行ステップ
                if "__WORKFLOW_COMPLETE__" in detected_signals:
                    current_step = 3 # 返信生成ステップへ移行
                    append_to_log(workflow_log_file_path, "システム: ワークフロー完了シグナル受信．返信生成ステップに移行します．\n---")
                    logger.info("--- ステップ3へ移行: 返信生成 ---")
                    state_transitioned_this_iteration = True
                else:
                    logger.info(f"ステップ2: 完了シグナルなし．必要であれば次の繰り返しで作業を継続します．")
                    append_to_log(workflow_log_file_path, "システム: ステップ2の作業を継続します．\n---")

            elif current_step == 3: # 返信生成ステップ
                if "__REPLY_GENERATED__" in detected_signals:
                    logger.info("--- 返信生成完了．ワークフローを終了し，Discordボットに応答を返します． ---")
                    append_to_log(workflow_log_file_path, f"システム: 返信生成完了．ワークフロー終了．\n最終返信テキスト(先頭100文字): {final_reply_text_from_tool[:100]}...\n出力ファイル: {final_output_files_from_tool}\n---")
                    return {
                        "status": "success",
                        "reply_text": final_reply_text_from_tool,
                        "output_files": final_output_files_from_tool,
                        "workflow_id": workflow_id,
                        "final_workspace_path": workflow_workspace_path,
                        "log_file_path": workflow_log_file_path
                    }
                else:
                    logger.warning(f"ステップ3: __REPLY_GENERATED__ シグナルが検出されませんでした．make_replyツールが正しく呼び出されなかった可能性があります．")
                    append_to_log(workflow_log_file_path, "システム警告: 返信が生成されませんでした．LLMの思考（make_reply呼び出し）を確認してください．\n---")

            elif current_step == 4: # フィードバック処理ステップ
                if "__GOAL_SET__" in detected_signals:
                    current_step = 2 # フィードバック処理完了，作業実行へ
                    append_to_log(workflow_log_file_path, "システム: 目標再設定完了．作業実行ステップに移行します．\n---")
                    logger.info("--- ステップ2へ移行: 作業実行 ---")
                    state_transitioned_this_iteration = True
                else:
                    logger.info(f"ステップ4: __WORKFLOW_COMPLETE__ シグナルなし．フィードバック処理/計画見直しを継続します．")
                    append_to_log(workflow_log_file_path, "システム: ステップ4のフィードバック処理を継続します．\n---")

            # 状態遷移がなかった場合のフォールバック処理
            if not state_transitioned_this_iteration:
                # ステップ1, 3, 4で停滞している場合は警告/エラー (ステップ2は複数回ループが正常)
                if current_step in [1, 3, 4]:
                    logger.warning(f"ワークフローがステップ {current_step} で状態遷移せずに停滞している可能性があります．(繰り返し: {iteration_count})")
                    if iteration_count >= 3:
                        logger.error(f"ワークフローがステップ {current_step} で3回以上停滞したため，異常終了します．")
                        append_to_log(workflow_log_file_path, f"## エラー: ワークフロー異常終了 (ステップ {current_step} で停滞)\n---")
                        return {
                            "status": "error", "reply_text": f"ワークフロー実行エラー: ステップ {current_step} で処理が停滞しました．",
                            "output_files": [], "workflow_id": workflow_id,
                            "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path
                        }
                else: # ステップ2での停滞
                    logger.debug(f"ワークフローがステップ {current_step} で状態遷移しませんでした．作業継続を試みます．(繰り返し: {iteration_count})")

        logger.warning(f"ワークフロー '{workflow_id}' が最大繰り返し回数 ({max_iterations}) に達しました．処理を終了します．")
        append_to_log(workflow_log_file_path, f"## システム: 最大繰り返し回数到達．ワークフロー終了．\n---")
        return {
            "status": "max_iterations_reached",
            "reply_text": "ワークフローが最大繰り返し回数に達しました．詳細はログを確認してください．",
            "output_files": [],
            "workflow_id": workflow_id,
            "final_workspace_path": workflow_workspace_path,
            "log_file_path": workflow_log_file_path
        }

    # この部分には通常到達しないはず
    logger.error(f"ワークフロー '{workflow_id}' がメインループ外で予期せず終了しました．")
    return {
        "status": "error", "reply_text": "ワークフローが予期せず終了しました．", "output_files": [],
        "workflow_id": workflow_id, "final_workspace_path": workflow_workspace_path, "log_file_path": workflow_log_file_path
    }

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stdout)

    logger.info("main.py をテスト目的で直接実行します．")

    from config import ensure_directories, check_tool_scripts
    ensure_directories()
    if not check_tool_scripts():
        logger.critical("一部のMCPツールスクリプトが見つからないため，テストを中止します．")
        sys.exit(1)

    current_workflow_id = None
    while True:
        if current_workflow_id:
            user_query = input(f"ワークフロー {current_workflow_id} に追加で指示/フィードバックを入力してください ('終了'で終了, '新規'で新規開始):\n> ")
            if user_query.lower() == '終了':
                break
            elif user_query.lower() == '新規':
                current_workflow_id = None
                user_query = input("新しいタスクを入力してください:\n> ")
                if not user_query or user_query.lower() == '終了':
                    break
                result = asyncio.run(run_workflow(initial_message=user_query, attachments=[])) # 新規開始
            else:
                result = asyncio.run(run_workflow(
                    initial_message="継続時のダミーメッセージ", # initial_message は継続時には使われないが引数として必要
                    existing_workflow_id=current_workflow_id,
                    user_feedback_for_continuation=user_query
                ))
        else:
            user_query = input("実行したいタスクを入力してください（'終了'で終了）:\n> ")
            if user_query.lower() == '終了':
                break
            if not user_query:
                continue
            result = asyncio.run(run_workflow(initial_message=user_query, attachments=[])) # 新規開始

        logger.info(f"\n--- ワークフローテスト結果 ---")
        logger.info(f"ステータス: {result.get('status')}")
        logger.info(f"返信テキスト: {result.get('reply_text')}")
        logger.info(f"出力ファイル: {result.get('output_files')}")
        logger.info(f"ワークフローID: {result.get('workflow_id')}")
        logger.info(f"ワークスペースパス: {result.get('final_workspace_path')}")
        logger.info(f"ログファイルパス: {result.get('log_file_path')}")

        if result.get('status') in ["success", "max_iterations_reached"]:
            current_workflow_id = result.get('workflow_id')
        else:
            current_workflow_id = None

    logger.info("テスト実行を終了します．")