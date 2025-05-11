import discord
import os
import logging
import uuid
import asyncio
import traceback
import re
from pathlib import Path

import main as workflow_orchestrator

from config import (
    DISCORD_BOT_TOKEN, TEMP_ATTACHMENT_DIR,
    BASE_PROJECT_WORKSPACE_DIR,
    PRIORITY_NEW_TASK, PRIORITY_CONTINUATION_TASK
)
import sys

# ロギング設定
logger = logging.getLogger('discord_bot')
logger.setLevel(logging.INFO)
if not logger.handlers:
    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s'
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(log_format))
    logger.addHandler(ch)

Path(TEMP_ATTACHMENT_DIR).mkdir(parents=True, exist_ok=True)
Path(BASE_PROJECT_WORKSPACE_DIR).mkdir(parents=True, exist_ok=True)

# Discordボットの Intents 設定
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
client = discord.Client(intents=intents)

# タスクキューの初期化
# 優先度付きキューを使用: (優先度, タスク詳細)
# 優先度の数値が小さいほど優先度が高い
task_queue = asyncio.PriorityQueue()

# バックグラウンド・ワーカー
async def workflow_task_processor():
    logger.info("ワークフロー・タスクプロセッサーを開始しました．")
    while True:
        task_details = None
        discord_message_obj = None
        processing_feedback_msg = None

        try:
            priority, task_details = await task_queue.get()
            discord_message_obj: discord.Message = task_details.pop("discord_message_obj")

            try:
                processing_feedback_msg = await discord_message_obj.channel.send(
                    f"🤖 リクエストを処理中です (ワークフローID: {task_details.get('existing_workflow_id', '新規')}). しばらくお待ちください...",
                    reference=discord_message_obj
                )
            except Exception as e_feedback:
                logger.warning(f"処理中メッセージの送信に失敗しました: {e_feedback}", exc_info=True)
                processing_feedback_msg = None

            logger.info(f"タスク処理開始 (優先度: {priority}) ユーザー: {discord_message_obj.author.id}, "
                        f"初回メッセージ(先頭50字): '{task_details.get('initial_message', '')[:50]}...', "
                        f"既存WF ID: {task_details.get('existing_workflow_id')}")

            workflow_result = {}
            try:
                workflow_result = await workflow_orchestrator.run_workflow(
                    initial_message=task_details["initial_message"],
                    attachments=task_details.get("attachments"), # TEMP_ATTACHMENT_DIR 内のファイルパスリスト
                    existing_workflow_id=task_details.get("existing_workflow_id"), # 継続の場合のみ None 以外になる
                    user_feedback_for_continuation=task_details.get("user_feedback_for_continuation") # 継続の場合のみ新しいメッセージ内容をフィードバックとする
                )
                logger.info(f"ワークフロー {workflow_result.get('workflow_id')} の結果: ステータス {workflow_result.get('status')}")

            except Exception as e_wf_unhandled:
                logger.error(f"run_workflow 呼び出し中の未ハンドルエラー: {e_wf_unhandled}", exc_info=True)
                workflow_result = {
                    "status": "critical_error",
                    "reply_text": f"リクエスト処理中にシステム内部で重大なエラーが発生しました: {e_wf_unhandled}",
                    "output_files": [],
                    "workflow_id": task_details.get('existing_workflow_id') or task_details.get('generated_workflow_id', "不明"),
                    "final_workspace_path": None
                }
            finally:
                if processing_feedback_msg:
                    try:
                        await processing_feedback_msg.delete()
                    except discord.HTTPException:
                        pass

            reply_text = workflow_result.get("reply_text", "ワークフローは完了しましたが，特定のメッセージはありません．")
            output_files_relative = workflow_result.get("output_files", [])
            final_workspace_path = workflow_result.get("final_workspace_path")
            returned_workflow_id = workflow_result.get("workflow_id", "N/A")
            status = workflow_result.get("status", "不明")

            response_header = f"**ワークフローID:** `{returned_workflow_id}`\n"
            if task_details and task_details.get("existing_workflow_id"):
                response_header += f"(継続元ワークフローID: `{task_details.get('existing_workflow_id')}`)\n"
            response_header += f"**ステータス:** {status.replace('_', ' ').title()}\n\n"

            full_reply_content = response_header + reply_text

            files_to_send_to_discord = []
            if final_workspace_path and output_files_relative:
                for rel_path in output_files_relative:
                    if not isinstance(rel_path, str) or not rel_path:
                        logger.warning(f"不正な相対ファイルパスを受け取りました: '{rel_path}' (WF ID: {returned_workflow_id})")
                        full_reply_content += f"\n⚠️ システム警告: エージェントから不正なファイルパス ('{rel_path}') が指定されました．"
                        continue

                    abs_path = os.path.join(final_workspace_path, rel_path)
                    if os.path.exists(abs_path) and os.path.isfile(abs_path):
                        try:
                            if os.path.getsize(abs_path) > 25 * 1024 * 1024:
                                logger.warning(f"ファイルサイズがDiscordの制限を超えています: {abs_path}")
                                full_reply_content += f"\n⚠️ ファイル '{os.path.basename(rel_path)}' はサイズ制限のため送信できません．"
                            else:
                                files_to_send_to_discord.append(discord.File(abs_path))
                                logger.info(f"送信準備完了 (Discord用ファイル): {abs_path}")
                        except Exception as e_file:
                            logger.error(f"discord.File オブジェクト作成失敗: {abs_path}, エラー: {e_file}", exc_info=True)
                            full_reply_content += f"\n⚠️ ファイル '{os.path.basename(rel_path)}' の送信準備中にエラーが発生しました．"
                    else:
                        logger.warning(f"エージェント指定の出力ファイルが見つからないか，ファイルではありません: {abs_path} (相対パス: {rel_path}) (WF ID: {returned_workflow_id})")
                        full_reply_content += f"\n⚠️ エージェントがファイル '{os.path.basename(rel_path)}' に言及しましたが，見つからないかアクセスできません．"

            MAX_MESSAGE_LENGTH = 1950

            if len(full_reply_content) <= MAX_MESSAGE_LENGTH and (not files_to_send_to_discord or len(files_to_send_to_discord) == 1):
                await discord_message_obj.reply(content=full_reply_content, files=files_to_send_to_discord if files_to_send_to_discord else None, allowed_mentions=discord.AllowedMentions.none())
            else:
                first_part_sent = False
                remaining_text_to_send = full_reply_content

                while remaining_text_to_send:
                    current_chunk_to_send = remaining_text_to_send[:MAX_MESSAGE_LENGTH]
                    remaining_text_to_send = remaining_text_to_send[MAX_MESSAGE_LENGTH:]

                    if not first_part_sent:
                        first_response_message = await discord_message_obj.reply(content=current_chunk_to_send, files=files_to_send_to_discord if files_to_send_to_discord else None, allowed_mentions=discord.AllowedMentions.none())
                        first_part_sent = True
                        reply_reference = first_response_message
                    else:
                        reply_reference = await discord_message_obj.channel.send(content=current_chunk_to_send, reference=reply_reference, allowed_mentions=discord.AllowedMentions.none())
                    await asyncio.sleep(0.5)

            logger.info(f"ユーザーへの返信完了 (WF ID: {returned_workflow_id})．")

        except Exception as e_processor_loop:
            logger.critical(f"重大エラー: workflow_task_processor ループで予期せぬエラー: {e_processor_loop}", exc_info=True)
            error_reply_content = f"🚨 申し訳ありません，タスク処理システムで重大なエラーが発生しました．開発チームに通知されました．\nエラー詳細: {e_processor_loop.__class__.__name__}: {e_processor_loop}"
            if 'discord_message_obj' in locals() and discord_message_obj:
                try:
                    await discord_message_obj.reply(error_reply_content, allowed_mentions=discord.AllowedMentions.none())
                except Exception as e_reply_critical:
                    logger.error(f"重大エラー通知の送信失敗: {e_reply_critical}")
            elif task_details and task_details.get("discord_message_obj"):
                try:
                    await task_details["discord_message_obj"].reply(error_reply_content, allowed_mentions=discord.AllowedMentions.none())
                except Exception as e_reply_critical:
                    logger.error(f"重大エラー通知の送信失敗 (task_detailsから): {e_reply_critical}")

        finally:
            if task_details and task_details.get("attachments"):
                for temp_file_path_to_clean in task_details["attachments"]:
                    try:
                        if os.path.exists(temp_file_path_to_clean):
                            os.remove(temp_file_path_to_clean)
                            logger.info(f"一時添付ファイルを削除しました: {temp_file_path_to_clean}")
                    except OSError as e_remove_temp:
                        logger.error(f"一時添付ファイル '{temp_file_path_to_clean}' の削除エラー: {e_remove_temp}")
            if 'task_queue' in locals():
                try:
                    task_queue.task_done()
                except ValueError:
                    logger.warning("task_queue.task_done() の呼び出し中にエラーが発生しました (おそらく重複)．")


@client.event
async def on_ready():
    logger.info(f'ログイン成功: {client.user.name} (ID: {client.user.id})')
    logger.info(f'discord.py バージョン: {discord.__version__}')
    logger.info('Discordボットが起動し，メンション待機中です．')
    if not hasattr(client, '_task_processor_started_flag') or not client._task_processor_started_flag:
        asyncio.create_task(workflow_task_processor())
        client._task_processor_started_flag = True
        logger.info("タスクプロセッサーの起動を試みました．")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    is_mention = client.user.mentioned_in(message)
    is_reply_to_bot = message.reference and message.reference.resolved and message.reference.resolved.author == client.user

    if not is_mention and not is_reply_to_bot:
        return

    logger.info(f"メッセージ受信: {message.author.name} (ID: {message.author.id}), チャンネル: {message.channel.id}")

    bot_mention_pattern = f"<@!?{client.user.id}>"
    cleaned_content_text = re.sub(bot_mention_pattern, "", message.content).strip()

    temporary_attachment_paths = []
    if message.attachments:
        logger.info(f"{len(message.attachments)}個の添付ファイルを受信しました．")
        for attachment in message.attachments:
            safe_filename = "".join(c for c in attachment.filename if c.isalnum() or c in ['.', '_', '-']).rstrip('.')
            if not safe_filename: safe_filename = "attachment"
            temp_file_path = os.path.join(TEMP_ATTACHMENT_DIR, f"{uuid.uuid4()}_{safe_filename}")
            try:
                await attachment.save(temp_file_path)
                temporary_attachment_paths.append(temp_file_path)
                logger.info(f"添付ファイル '{attachment.filename}' を一時保存しました: '{temp_file_path}'")
            except Exception as e_attach_save:
                logger.error(f"添付ファイル '{attachment.filename}' の保存失敗: {e_attach_save}", exc_info=True)
                await message.reply(f"⚠️ 添付ファイル '{attachment.filename}' の保存中にエラーが発生しました．")
                for p_to_clean in temporary_attachment_paths:
                    try:
                        if os.path.exists(p_to_clean): os.remove(p_to_clean)
                    except OSError: pass
                return

    existing_workflow_id_from_reply = None
    user_feedback_for_continuation = cleaned_content_text

    if is_reply_to_bot:
        referenced_message_content = None
        try:
            referenced_message = message.reference.resolved

            if referenced_message:
                referenced_message_content = referenced_message.content
                logger.debug(f"リプライ元のメッセージ内容 (ID: {referenced_message.id}): '{referenced_message_content[:100]}...'")

                id_match = re.search(r"\*\*ワークフローID:\*\*\s*`?([a-zA-Z0-9_.\-]+)`?", referenced_message_content)

                if id_match:
                    existing_workflow_id_from_reply = id_match.group(1)
                    logger.info(f"ボットのメッセージへのリプライを検出．継続対象ワークフローID: {existing_workflow_id_from_reply}")
                else:
                    logger.warning(f"ボットのメッセージへのリプライですが，内容からワークフローIDを抽出できませんでした．元のメッセージ内容(先頭100字): '{referenced_message_content[:100]}...'")

            else:
                logger.warning(f"リプライ対象のメッセージ (ID: {message.reference.message_id}) の解決に失敗しました．")

        except Exception as e_ref_proc:
            logger.error(f"リプライ対象メッセージの処理中にエラー: {e_ref_proc}", exc_info=True)


    is_meaningful_new_input = bool(cleaned_content_text or temporary_attachment_paths)

    if not is_meaningful_new_input and not existing_workflow_id_from_reply:
        if is_mention:
            await message.reply("こんにちは！何かご用件やファイルがあれば教えてください．"
                                "以前の私のメッセージに返信する形で，作業を続けることもできます．", allowed_mentions=discord.AllowedMentions.none())
        elif is_reply_to_bot and not existing_workflow_id_from_reply:
            await message.reply("リプライありがとうございます．しかし，返信元のメッセージからワークフローIDを特定できませんでした．新しい指示やファイルがないため，このリプライは処理されません．", allowed_mentions=discord.AllowedMentions.none())
        return

    task_priority_level = PRIORITY_NEW_TASK
    initial_message_for_workflow = cleaned_content_text

    if existing_workflow_id_from_reply:
        task_priority_level = PRIORITY_CONTINUATION_TASK
        initial_message_for_workflow = f"ユーザーからのフィードバック (ワークフローID: {existing_workflow_id_from_reply} 向け)" if cleaned_content_text else f"ワークフロー継続要求 (ID: {existing_workflow_id_from_reply})"

        logger.info(f"継続タスクをキューに追加します (WF_ID: {existing_workflow_id_from_reply}, フィードバック(先頭50字): '{user_feedback_for_continuation[:50]}...')")

    elif is_reply_to_bot and not existing_workflow_id_from_reply and is_meaningful_new_input:
        await message.reply("リプライありがとうございます．返信元のメッセージからワークフローIDを特定できませんでした．新しい指示として，これは新規タスクとして処理を開始します．", allowed_mentions=discord.AllowedMentions.none())
        logger.warning("リプライだがID抽出失敗．新しい入力があったため，新規タスクとしてキューに追加します．")

    else:
        logger.info(f"新規タスクをキューに追加します (メッセージ(先頭50字): '{initial_message_for_workflow[:50]}...', 添付ファイル数: {len(temporary_attachment_paths)})")

    task_data_for_queue = {
        "initial_message": initial_message_for_workflow,
        "attachments": temporary_attachment_paths,
        "discord_message_obj": message, # 返信先として使用
        "existing_workflow_id": existing_workflow_id_from_reply,
        "user_feedback_for_continuation": user_feedback_for_continuation if existing_workflow_id_from_reply else None,
    }

    await task_queue.put((task_priority_level, task_data_for_queue))
    try:
        await message.add_reaction("📨")
    except discord.HTTPException:
        pass
    logger.info(f"タスクを優先度 {task_priority_level} でキューに追加しました．現在のキューサイズ: {task_queue.qsize()}")

if __name__ == '__main__':
    logger.info("Discordボットを起動します...")

    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        logger.critical("環境変数または .env ファイルに DISCORD_BOT_TOKEN が設定されていないか，デフォルト値のままです．")
        logger.critical("Discordボットを終了します．DISCORD_BOT_TOKEN を正しく設定してください．")
        sys.exit(1)

    from config import ensure_directories as ensure_config_dirs
    ensure_config_dirs()
    from config import check_tool_scripts as check_mcp_scripts
    if not check_mcp_scripts():
        logger.warning("いくつかのツールスクリプトが見つかりません．設定を確認してください．一部機能が利用できない可能性があります．")

    try:
        client.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure:
        logger.critical("Discordへのログインに失敗しました．トークンが無効である可能性があります．")
    except Exception as e_bot_run:
        logger.critical(f"ボット実行中に予期せぬエラーが発生しました: {e_bot_run}", exc_info=True)
        traceback.print_exc()