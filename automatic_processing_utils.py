# automatic_processing_utils.py
import os
import subprocess
import sys
from datetime import datetime
import logging
from typing import Dict, Any, Tuple

# image_to_text_tool は main.py と同じ階層にあると仮定
try:
    from image_to_text_tool import process_images_for_manifest, _calculate_file_hash as calculate_file_hash_from_tool
except ImportError:
    logging.getLogger(__name__).critical(
        "Error: Could not import 'image_to_text_tool' from automatic_processing_utils.py.", exc_info=True
    )
    # ダミー関数やクラスを定義してエラーを防ぐ (本番では修正が必要)
    def process_images_for_manifest(workspace_path: str, image_manifest_data: Dict[str, Any], log_messages_for_main_log: list):
        return image_manifest_data, [], False
    def calculate_file_hash_from_tool(filepath: str) -> str:
        return ""

logger = logging.getLogger(__name__)
FILE_MANIFEST_NAME = "file_manifest.json" # main.py と共有
RESEARCH_NOTES_FILENAME = "research_notes.md" # main.py と共有

async def run_automatic_file_processing(
    workflow_workspace_path: str,
    current_file_manifest: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    logger.info("--- 自動ファイル処理開始 ---")
    console_log_messages = [] 
    
    temp_img_proc_logs_for_main_md: list = []
    current_file_manifest, _, img_manifest_updated = process_images_for_manifest(
        workflow_workspace_path,
        current_file_manifest,
        temp_img_proc_logs_for_main_md
    )
    if img_manifest_updated:
        console_log_messages.append("画像マニフェストが更新されました。")

    py_manifest_updated = False
    found_py_files = False
    for root, _, files in os.walk(workflow_workspace_path):
        for file in files:
            if file.lower().endswith(".py"):
                found_py_files = True
                py_abs_path = os.path.join(root, file)
                py_rel_path = os.path.relpath(py_abs_path, workflow_workspace_path)
                
                current_hash = calculate_file_hash_from_tool(py_abs_path)
                if not current_hash:
                    console_log_messages.append(f"警告 (Python): `{py_rel_path}` のハッシュ計算失敗。スキップ。")
                    continue

                entry = current_file_manifest["files"].get(py_rel_path)
                needs_processing = False
                if entry is None or entry.get("type") != "python" or entry.get("hash") != current_hash:
                    needs_processing = True
                    logger.info(f"新規または変更されたPythonスクリプト検出: {py_rel_path}")
                
                if needs_processing:
                    py_manifest_updated = True
                    script_content = ""
                    try:
                        with open(py_abs_path, "r", encoding="utf-8") as f_py:
                            script_content = f_py.read()
                    except Exception as e_read:
                        console_log_messages.append(f"エラー (Python): `{py_rel_path}` の読み込み失敗 - {e_read}")
                        logger.error(f"Failed to read Python script {py_rel_path}: {e_read}", exc_info=True)
                        current_file_manifest["files"][py_rel_path] = {
                            "type": "python", "hash": current_hash,
                            "content_logged_timestamp": datetime.now().isoformat(),
                            "status": "error_reading", "error_message": str(e_read),
                            "last_processed_timestamp": datetime.now().isoformat()
                        }
                        continue

                    logger.info(f"Pythonスクリプト `{py_rel_path}` を実行します...")
                    try:
                        proc_result = subprocess.run(
                            [sys.executable, py_abs_path], 
                            capture_output=True, text=True, timeout=30, cwd=workflow_workspace_path,
                            encoding='utf-8', errors='replace'
                        )
                        stdout = proc_result.stdout
                        stderr = proc_result.stderr
                        return_code = proc_result.returncode
                        
                        logger.info(f"Python script {py_rel_path} executed. RC: {return_code}. Stdout: {len(stdout)} chars, Stderr: {len(stderr)} chars.")

                        current_file_manifest["files"][py_rel_path] = {
                            "type": "python", "hash": current_hash,
                            "content_logged_timestamp": datetime.now().isoformat(),
                            "execution_result": {
                                "stdout": stdout, "stderr": stderr, "return_code": return_code,
                                "timestamp": datetime.now().isoformat()
                            },
                            "status": "executed_ok" if return_code == 0 else "executed_with_error",
                            "last_processed_timestamp": datetime.now().isoformat()
                        }
                    except subprocess.TimeoutExpired:
                        console_log_messages.append(f"エラー (Python): `{py_rel_path}` の実行がタイムアウトしました。")
                        logger.warning(f"Python script {py_rel_path} timed out.")
                        current_file_manifest["files"][py_rel_path] = {
                            "type": "python", "hash": current_hash,
                            "content_logged_timestamp": datetime.now().isoformat(),
                            "execution_result": {"stdout": "", "stderr": "Execution timed out.", "return_code": -1},
                            "status": "execution_timeout",
                            "last_processed_timestamp": datetime.now().isoformat()
                        }
                    except Exception as e_exec:
                        console_log_messages.append(f"エラー (Python): `{py_rel_path}` の実行中に予期せぬエラー - {e_exec}")
                        logger.error(f"Unexpected error executing Python script {py_rel_path}: {e_exec}", exc_info=True)
                        current_file_manifest["files"][py_rel_path] = {
                            "type": "python", "hash": current_hash,
                            "content_logged_timestamp": datetime.now().isoformat(),
                            "execution_result": {"stdout": "", "stderr": f"Unexpected execution error: {e_exec}", "return_code": -1},
                            "status": "execution_exception", "error_message": str(e_exec),
                            "last_processed_timestamp": datetime.now().isoformat()
                        }

    if found_py_files and py_manifest_updated:
        console_log_messages.append("Pythonスクリプトのマニフェストが更新されました。")

    txt_manifest_updated = False
    found_txt_files = False
    text_extensions = ['.txt', '.md', '.json', '.csv', '.html', '.css', '.js']
    for root, _, files in os.walk(workflow_workspace_path):
        if FILE_MANIFEST_NAME in files and root == workflow_workspace_path :
             files_to_process = [f for f in files if f != FILE_MANIFEST_NAME]
        else:
             files_to_process = files

        for file in files_to_process:
            if any(file.lower().endswith(ext) for ext in text_extensions):
                found_txt_files = True
                txt_abs_path = os.path.join(root, file)
                txt_rel_path = os.path.relpath(txt_abs_path, workflow_workspace_path)

                current_hash = calculate_file_hash_from_tool(txt_abs_path)
                if not current_hash:
                    console_log_messages.append(f"警告 (Text): `{txt_rel_path}` のハッシュ計算失敗。スキップ。")
                    continue
                
                entry = current_file_manifest["files"].get(txt_rel_path)
                needs_processing = False
                if entry is None or entry.get("type") not in ["text", "markdown_research_notes"] or entry.get("hash") != current_hash:
                    needs_processing = True
                    logger.info(f"新規または変更されたテキスト/MDファイル検出: {txt_rel_path}")

                if needs_processing:
                    txt_manifest_updated = True
                    file_content = ""
                    try:
                        with open(txt_abs_path, "r", encoding="utf-8") as f_txt:
                            file_content = f_txt.read()
                        
                        file_type = "text"
                        if txt_rel_path == RESEARCH_NOTES_FILENAME:
                            file_type = "markdown_research_notes"

                        current_file_manifest["files"][txt_rel_path] = {
                            "type": file_type, 
                            "hash": current_hash,
                            "content_char_count": len(file_content),
                            "status": "processed",
                            "last_processed_timestamp": datetime.now().isoformat()
                        }
                    except Exception as e_read_txt:
                        console_log_messages.append(f"エラー (Text): `{txt_rel_path}` の読み込み失敗 - {e_read_txt}")
                        logger.error(f"Failed to read text file {txt_rel_path}: {e_read_txt}", exc_info=True)
                        current_file_manifest["files"][txt_rel_path] = {
                            "type": "text", "hash": current_hash,
                            "status": "error_reading", "error_message": str(e_read_txt),
                            "last_processed_timestamp": datetime.now().isoformat()
                        }
    
    if found_txt_files and txt_manifest_updated:
        console_log_messages.append("テキスト/MDファイルのマニフェストが更新されました。")
    
    overall_manifest_updated = img_manifest_updated or py_manifest_updated or txt_manifest_updated
    
    if console_log_messages: # コンソールにはログを出力
        logger.debug("自動ファイル処理コンソールログ:\n" + "\n".join([f"- {log}" for log in console_log_messages]))

    logger.info(f"--- 自動ファイル処理完了 (マニフェスト更新: {overall_manifest_updated}) ---")
    return current_file_manifest, overall_manifest_updated
