# workflow_setup_utils.py
import os
import shutil
import uuid
from datetime import datetime
import logging
from typing import Dict, Any, Tuple, List

from workflow_log_utils import append_to_log # main と同じ階層にある想定
from file_manifest_utils import load_file_manifest, save_file_manifest # 同上

logger = logging.getLogger(__name__)

# main.py から BASE_PROJECT_WORKSPACE_DIR と BASE_WORKFLOW_LOGS_DIR を渡す必要がある
# もしくは config から直接インポートする
from config import BASE_PROJECT_WORKSPACE_DIR, BASE_WORKFLOW_LOGS_DIR


def setup_new_workflow(
    initial_message: str,
    attachments: List[str] | None
) -> Tuple[str, str, str, Dict[str, Any], str]:
    """新規ワークフローのセットアップ"""
    workflow_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    workflow_workspace_path = os.path.join(BASE_PROJECT_WORKSPACE_DIR, f"workflow_{workflow_id}")
    workflow_log_file_path = os.path.join(BASE_WORKFLOW_LOGS_DIR, f"workflow_{workflow_id}.md")

    os.makedirs(workflow_workspace_path, exist_ok=True)
    os.makedirs(os.path.dirname(workflow_log_file_path), exist_ok=True)

    with open(workflow_log_file_path, "w", encoding="utf-8") as f:
        f.write(f"# ワークフローログ\n") 
        f.write(f"ID: {workflow_id}\n")
        f.write(f"ワークスペース: `{workflow_workspace_path}`\n")
        f.write(f"初回ユーザーリクエスト: {initial_message}\n")
    logger.info(f"新規ワークフロー '{workflow_id}' を開始しました．.mdログ: '{workflow_log_file_path}'")
    
    file_manifest = load_file_manifest(workflow_workspace_path)

    if attachments:
        attachment_log_entries = []
        for temp_att_path in attachments:
            if os.path.exists(temp_att_path):
                filename = os.path.basename(temp_att_path)
                dest_path = os.path.join(workflow_workspace_path, filename)
                try:
                    shutil.copy(temp_att_path, dest_path)
                    logger.info(f"添付ファイル '{filename}' を '{dest_path}' にコピーしました．")
                    attachment_log_entries.append(f"- {filename}")
                except Exception as e_copy:
                    logger.error(f"添付ファイルコピー失敗: {filename} - {e_copy}")
                    attachment_log_entries.append(f"- {filename} (コピー失敗: {e_copy})")
            else:
                 attachment_log_entries.append(f"- {temp_att_path} (パス無効)")
        if attachment_log_entries:
             append_to_log(workflow_log_file_path, f"## ユーザーからのファイル:\n" + "\n".join(attachment_log_entries) + "\n")
    
    return workflow_id, workflow_workspace_path, workflow_log_file_path, file_manifest, initial_message

def setup_existing_workflow(
    existing_workflow_id: str,
    initial_message_on_continuation: str, # ダミーまたはフォールバック用
    attachments: List[str] | None,
    user_feedback: str | None
) -> Tuple[str, str, str, Dict[str, Any], str, str | None]:
    """既存ワークフローのセットアップ"""
    workflow_id = existing_workflow_id
    workflow_workspace_path = os.path.join(BASE_PROJECT_WORKSPACE_DIR, f"workflow_{workflow_id}")
    workflow_log_file_path = os.path.join(BASE_WORKFLOW_LOGS_DIR, f"workflow_{workflow_id}.md")
    
    if not os.path.exists(workflow_workspace_path) or not os.path.exists(workflow_log_file_path):
        err_msg = f"エラー: 既存ワークフローのデータ (ID: {workflow_id}) が見つかりません．"
        # ここでエラーをraiseするか、呼び出し元で処理するか。今回は呼び出し元で処理。
        raise FileNotFoundError(err_msg) 
    
    logger.info(f"既存ワークフローを継続します: {workflow_id}")
    file_manifest = load_file_manifest(workflow_workspace_path)
    
    from workflow_log_utils import read_log # ここでインポート
    import re # ここでインポート

    log_content_full = read_log(workflow_log_file_path)
    original_initial_request = initial_message_on_continuation # デフォルト
    match = re.search(r"初回ユーザーリクエスト: (.+)\n", log_content_full)
    if match:
        original_initial_request = match.group(1).strip()
    else:
        logger.warning(f".md ログファイルから初回ユーザーリクエストを抽出できませんでした。")
        if initial_message_on_continuation == "継続時のダミーメッセージ":
             original_initial_request = "（初回リクエスト不明）"


    if attachments:
        attachment_log_entries = []
        for temp_att_path in attachments:
            if os.path.exists(temp_att_path):
                filename = os.path.basename(temp_att_path)
                dest_path = os.path.join(workflow_workspace_path, filename)
                try:
                    shutil.copy(temp_att_path, dest_path)
                    logger.info(f"添付ファイル '{filename}' を '{dest_path}' にコピーしました．")
                    attachment_log_entries.append(f"- {filename}")
                    if filename in file_manifest["files"]: 
                        file_manifest["files"][filename]["hash"] = "FORCE_REPROCESS_" + str(uuid.uuid4())[:8]
                except Exception as e_copy:
                    logger.error(f"継続時の添付ファイルコピー失敗: {filename} - {e_copy}")
                    attachment_log_entries.append(f"- {filename} (コピー失敗: {e_copy})")
            else:
                attachment_log_entries.append(f"- {temp_att_path} (パス無効)")
        if attachment_log_entries:
            append_to_log(workflow_log_file_path, f"## ユーザーからの追加ファイル:\n" + "\n".join(attachment_log_entries) + "\n")
        save_file_manifest(workflow_workspace_path, file_manifest) # マニフェスト更新を保存

    if user_feedback:
        append_to_log(workflow_log_file_path, f"\n## ユーザーフィードバック (最重要):\n---\n{user_feedback}\n---\n")
        
    return workflow_id, workflow_workspace_path, workflow_log_file_path, file_manifest, original_initial_request, user_feedback
