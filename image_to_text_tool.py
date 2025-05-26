import sys
import os
import logging
import json
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv, find_dotenv
from typing import List, Tuple, Dict, Any
import hashlib
from datetime import datetime

# .env ファイルから環境変数を読み込む
load_dotenv(find_dotenv())
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# このモジュール専用のロガーを設定
# main.py のロガーと区別するため、異なる名前空間を使用
tool_logger = logging.getLogger(f"{__name__}_image_tool")
if not tool_logger.handlers: # ハンドラが重複して追加されるのを防ぐ
    handler = logging.StreamHandler(sys.stdout)
    # フォーマットにモジュール名がわかるように印を追加
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s [image_to_text_tool]')
    handler.setFormatter(formatter)
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.INFO) # INFOレベル以上を標準出力に表示

class ImageExtractionError(Exception):
    """画像テキスト抽出に関するカスタムエラー"""
    pass

def _calculate_file_hash(filepath: str) -> str:
    """ファイルのSHA256ハッシュを計算する"""
    sha256_hash = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        tool_logger.error(f"ハッシュ計算エラー: ファイルが見つかりません - {filepath}")
        return ""
    except Exception as e:
        tool_logger.error(f"ハッシュ計算中に予期せぬエラー: {filepath} - {e}", exc_info=True)
        return ""

def extract_text_from_image_api(image_path: str, log_messages_for_main_log: List[str]) -> str:
    """
    指定された画像ファイルからテキストを抽出する (API呼び出し部分)。
    log_messages_for_main_log は main.py のワークフローログに追加するためのリスト。
    """
    if not os.path.exists(image_path):
        msg = f"エラー: 画像ファイルが見つかりません - `{image_path}`"
        log_messages_for_main_log.append(msg)
        tool_logger.error(f"画像ファイルが見つかりません: {image_path}") # ツール自身のログ
        raise FileNotFoundError(f"Image file not found: {image_path}")

    if not GOOGLE_API_KEY:
        error_msg = "Error: GOOGLE_API_KEY environment variable not set."
        log_messages_for_main_log.append(f"エラー: {error_msg}")
        tool_logger.error(error_msg) # ツール自身のログ
        raise ImageExtractionError(error_msg)

    genai.configure(api_key=GOOGLE_API_KEY)

    try:
        model = genai.GenerativeModel('gemini-2.0-flash')

        img = Image.open(image_path)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
            tool_logger.debug(f"Converted RGBA to RGB for {image_path}")

        tool_logger.info(f"Calling Gemini API for image: {image_path}")
        response = model.generate_content(["画像に含まれるテキストをすべて抽出してください。", img])
        response.resolve()
        tool_logger.info(f"Gemini API call completed for image: {image_path}")

        extracted_text = ""
        if hasattr(response, 'text') and response.text:
            extracted_text = response.text.strip()
        elif response.candidates:
            try:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        for part in candidate.content.parts:
                            if hasattr(part, 'text'):
                                extracted_text += part.text + " "
                extracted_text = extracted_text.strip()
            except Exception as e_parts:
                tool_logger.warning(f"API応答のpartsからのテキスト抽出試行中にエラー: {e_parts} for {image_path}", exc_info=True)

        if not extracted_text:
            tool_logger.warning(f"No text extracted from {image_path} (API response empty or no text part).")

        return extracted_text

    except FileNotFoundError:
        raise
    except Exception as e:
        error_msg = f"Error processing image {image_path} with API: {e}"
        log_messages_for_main_log.append(f"エラー（API処理中）: 画像 `{os.path.basename(image_path)}` - {e}")
        tool_logger.error(error_msg, exc_info=True) # ツール自身のログ (詳細情報付き)
        raise ImageExtractionError(error_msg) from e


def process_images_for_manifest(
    workspace_path: str,
    image_manifest_data: Dict[str, Dict[str, Any]],
    log_messages_for_main_log: List[str]
) -> Tuple[Dict[str, Dict[str, Any]], List[str], bool]:
    """
    ワークスペース内の画像を処理し、新規または変更された画像からテキストを抽出する。
    抽出されたテキストは image_manifest_data (辞書) に記録される。

    Args:
        workspace_path: 画像ファイルが存在するワークスペースディレクトリのパス。
        image_manifest_data: キーが画像ファイルの相対パス、バリューがその画像の情報
                            (ハッシュ、抽出テキストなど) を持つ辞書。この関数内で更新される。
        log_messages_for_main_log: main.py のワークフローログに追加するためのメッセージリスト。

    Returns:
        - 更新された image_manifest_data (辞書)
        - log_messages_for_main_log (更新されたもの)
        - manifest_updated (bool): マニフェストが実際に更新されたかどうか
    """
    tool_logger.info(f"画像処理を開始します。ワークスペース: {workspace_path}")
    manifest_updated_flag = False

    if not os.path.isdir(workspace_path):
        error_msg = f"エラー: ワークスペースディレクトリが見つかりません - `{workspace_path}`"
        log_messages_for_main_log.append(error_msg)
        tool_logger.error(error_msg)
        return image_manifest_data, log_messages_for_main_log, manifest_updated_flag

    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']

    processed_image_count = 0
    new_or_changed_image_count = 0

    for root, _, files in os.walk(workspace_path):
        for file in files:
            file_lower = file.lower()
            if any(file_lower.endswith(ext) for ext in image_extensions):
                image_abs_path = os.path.join(root, file)
                # ワークスペースからの相対パスをキーとする
                image_rel_path = os.path.relpath(image_abs_path, workspace_path)

                current_hash = _calculate_file_hash(image_abs_path)
                if not current_hash:
                    log_messages_for_main_log.append(f"警告: `{image_rel_path}` のハッシュ計算に失敗。スキップします。")
                    tool_logger.warning(f"Failed to calculate hash for {image_rel_path}. Skipping.")
                    continue

                image_entry = image_manifest_data.get(image_rel_path)
                needs_processing = False
                if image_entry is None:
                    needs_processing = True
                    tool_logger.info(f"新規画像検出: {image_rel_path}")
                elif image_entry.get("hash") != current_hash:
                    needs_processing = True
                    tool_logger.info(f"変更された画像検出: {image_rel_path} (旧ハッシュ: {image_entry.get('hash', 'N/A')}, 新ハッシュ: {current_hash})")

                if needs_processing:
                    new_or_changed_image_count += 1
                    manifest_updated_flag = True
                    extracted_text_content = ""
                    error_info = None
                    try:
                        extracted_text_content = extract_text_from_image_api(image_abs_path, log_messages_for_main_log)
                    except FileNotFoundError: 
                        error_info = f"ファイルが見つかりません (処理中): {image_rel_path}"
                        tool_logger.error(f"File not found during processing of {image_rel_path} (should have been caught earlier).")
                    except ImageExtractionError as e:
                        error_info = f"画像テキスト抽出エラー: {e}"
                        tool_logger.warning(f"ImageExtractionError for {image_rel_path}: {e}")
                    except Exception as e_unexpected:
                        error_info = f"予期せぬエラー (画像処理中): {e_unexpected}"
                        tool_logger.error(f"Unexpected error during text extraction for {image_rel_path}: {e_unexpected}", exc_info=True)

                    current_time = datetime.now().isoformat()
                    image_manifest_data[image_rel_path] = {
                        "type": "image",
                        "hash": current_hash,
                        "extracted_text": extracted_text_content if not error_info else f"[エラーのためテキスト抽出失敗: {error_info}]",
                        "last_processed_timestamp": current_time,
                        "status": "error" if error_info else "processed"
                    }
                    if error_info:
                        image_manifest_data[image_rel_path]["error_message"] = error_info
                processed_image_count +=1

    if new_or_changed_image_count > 0:
        log_messages_for_main_log.append(f"画像処理: {new_or_changed_image_count} 件の新規または変更された画像を処理し、マニフェストを更新しました。")
    elif processed_image_count > 0 :
        log_messages_for_main_log.append(f"画像処理: 新規または変更された画像はありませんでした。({processed_image_count} 件の既存画像を確認)")
    else:
        log_messages_for_main_log.append("画像処理: ワークスペース内に処理対象の画像ファイルは見つかりませんでした。")

    tool_logger.info(f"画像処理完了。処理対象画像数: {processed_image_count}, 新規/変更画像数: {new_or_changed_image_count}")
    return image_manifest_data, log_messages_for_main_log, manifest_updated_flag