# tools/bootstrap_path.py
import sys
import os

def add_project_root_to_sys_path():
    """
    このモジュールが置かれている場所を基準にプロジェクトルートを計算し，
    sys.path に追加する．
    """
    # このファイルのディレクトリ (tools/)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # プロジェクトルートディレクトリ (tools/ の一つ上のディレクトリ)
    project_root = os.path.abspath(os.path.join(current_dir, os.pardir))

    # プロジェクトルートがsys.pathに含まれていない場合のみ追加
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        # print(f"Added {project_root} to sys.path") # デバッグ用

# このファイルをインポートしただけでパスが設定されるように，関数を呼び出しておく
add_project_root_to_sys_path()