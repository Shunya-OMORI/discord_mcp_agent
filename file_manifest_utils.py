# file_manifest_utils.py
import os
import json
from datetime import datetime
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)
FILE_MANIFEST_NAME = "file_manifest.json" # main.py と共有

def load_file_manifest(workspace_path: str) -> Dict[str, Any]:
    """ワークスペースからファイルマニフェストを読み込む"""
    manifest_path = os.path.join(workspace_path, FILE_MANIFEST_NAME)
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"ファイルマニフェスト ({manifest_path}) のJSONデコードに失敗しました。新しいマニフェストを作成します。")
        except Exception as e:
            logger.error(f"ファイルマニフェスト ({manifest_path}) の読み込み中にエラー: {e}", exc_info=True)
    return {"files": {}, "version": "1.1", "last_updated": datetime.now().isoformat()}

def save_file_manifest(workspace_path: str, manifest_data: Dict[str, Any]):
    """ファイルマニフェストをワークスペースに保存する"""
    manifest_path = os.path.join(workspace_path, FILE_MANIFEST_NAME)
    manifest_data["last_updated"] = datetime.now().isoformat()
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=4, ensure_ascii=False)
        logger.debug(f"ファイルマニフェストを保存しました: {manifest_path}")
    except Exception as e:
        logger.error(f"ファイルマニフェスト ({manifest_path}) の保存中にエラー: {e}", exc_info=True)