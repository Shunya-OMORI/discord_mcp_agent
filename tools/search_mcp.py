import bootstrap_path #インポートするだけでOK
import sys
import workflow_log_utils
import urllib.parse
import requests
from bs4 import BeautifulSoup, Tag
from mcp.server.fastmcp import FastMCP
import time # 待機用
print(f"DEBUG: {__file__} が引数 {sys.argv} で開始されました．", file=sys.stderr)

# Orchestrator から渡されるワークフロー固有のログファイルパスを読み込む
# sys.argv[0] はスクリプト自身のパスなので，argv[1]以降を期待する
WORKFLOW_LOG_FILE = None
if len(sys.argv) > 1:
    WORKFLOW_LOG_FILE = sys.argv[1]

if WORKFLOW_LOG_FILE is None:
    print("エラー: ワークフローログファイルパスが指定されていません．", file=sys.stderr)
    print("Warning: Workflow log file path not provided for search tool. Logging may not work correctly.", file=sys.stderr)

mcp = FastMCP(name="Yahoo! JAPAN Search")

@mcp.tool()
def search(keyword: str, max_results: int = 10) -> str:
    """
    Yahoo! JAPAN 検索で指定されたキーワードを検索し，結果をMarkdown形式で返します．
    ページの説明文はウェブページのほんのごく一部であり，最新の内容でない場合もあるため，ページを開いて確認するようにしてください．

    Args:
        keyword (str): 検索キーワード．
        max_results (int, optional): 最大検索結果数．デフォルトは10．
                                    実際の検索結果数は `max_results` に近い値になります（Yahoo!の仕様による）

    Returns:
        str: 検索結果をMarkdown形式でまとめた文字列．
            各検索結果は，リンクのタイトルとURL，および説明文で構成されます．
            検索結果がない場合は空文字列を返します．

    Raises:
        requests.exceptions.RequestException: 検索リクエストが失敗した場合．
        AttributeError: HTML構造が期待どおりでない場合．

    Example:
        >>> search("カシミヤ マフラー",20)
        '# [カシミヤ マフラーとは - Yahoo!検索（画像）](https://search.yahoo.co.jp/image/search?p=%E3%82%AB%E3%82%B7%E3%83%9F%E3%83%A4+%E3%83%9E%E3%83%95%E3%83%A9%E3%83%BC&fr=news_srp)
        カシミヤ マフラー の画像検索結果．

        # [【楽天市場】カシミヤ マフラーの通販](https://search.rakuten.co.jp/search/mall/%E3%82%AB%E3%82%B7%E3%83%9F%E3%83%A4+%E3%83%9E%E3%83%95%E3%83%A9%E3%83%BC/)
        楽天市場-「カシミヤ マフラー」の通販！口コミで人気のおすすめカシミヤ マフラーをご紹介． ...
        ...'
    """
    resp_text = ""
    num_iterations = (max_results + 9) // 10 # max_resultsを10で割って切り上げ
    num_iterations = min(num_iterations, 5) # 無限ループ防止のため最大5回(50件)などに制限

    for i in range(num_iterations):
        begin_count = i * 10 + 1
        search_url = f"https://search.yahoo.co.jp/search?p={urllib.parse.quote_plus(keyword)}&qrw=0&b={begin_count}"

        try:
            response = requests.get(search_url, timeout=10) # タイムアウト設定
            response.raise_for_status() # HTTPエラーが発生した場合に例外を投げる
            res_html = BeautifulSoup(response.text, "lxml")

            search_items = res_html.select('div#web li') # id="web" の div 内の li 要素

            if not search_items:
                # 検索結果が見つからない場合，またはセレクタが合わない場合
                if i == 0: # 最初のページで結果がない場合のみメッセージを返す
                    return f"キーワード '{keyword}' の検索結果は見つかりませんでした．"
                else: # 2ページ目以降で結果がなくなった場合はループを抜ける
                    break

            for item in search_items:
                # タイトルとURLを含むaタグを探す
                link_tag = item.select_one('a')
                # 説明文を含むdivタグなどを探す
                description_tag = item.select_one('div')

                if link_tag and 'href' in link_tag.attrs:
                    title = link_tag.get_text(strip=True)
                    url = link_tag.attrs['href']
                    description = description_tag.get_text(strip=True) if description_tag else "説明文なし"

                    # 広告などの不要な結果を除外する簡単なチェック (URLやクラス名などで行う)
                    resp_text += f"# [{title}]({url})\n"
                    resp_text += f"{description}\n\n"

        except requests.exceptions.RequestException as e:
            # リクエスト失敗時のエラーハンドリング
            if i == 0: # 最初の試行で失敗した場合のみエラーを返す
                print(f"検索リクエスト中にエラーが発生しました: {e}", file=sys.stderr) # デバッグ用
                return f"検索リクエスト中にエラーが発生しました: {e}"
            else: # 途中でのエラーはログに記録するなどして，得られた結果で続行する
                print(f"Warning: 検索リクエスト中にエラー (ページ {i+1}): {e}", file=sys.stderr)
                break # エラーが発生したページ以降はスキップ
        except AttributeError:
            # BeautifulSoupでの要素検索に失敗した場合 (HTML構造が想定と異なる)
            if i == 0:
                print(f"エラー: Yahoo検索のHTML構造が変わったようです．", file=sys.stderr) # デバッグ用
                return f"エラー: Yahoo検索のHTML構造が変わったようです．"
            else:
                print(f"Warning: HTML構造解析エラー (ページ {i+1})", file=sys.stderr)
                break
        except Exception as e:
            if i == 0:
                print(f"予期せぬエラーが発生しました: {e}", file=sys.stderr) # デバッグ用
                return f"予期せぬエラーが発生しました: {e}"
            else:
                print(f"Warning: 予期せぬエラー (ページ {i+1}): {e}", file=sys.stderr)
                break

        time.sleep(0.5)

    if not resp_text:
        return f"キーワード '{keyword}' の検索結果は見つかりませんでした．"

    if WORKFLOW_LOG_FILE:
        workflow_log_utils.append_to_log(WORKFLOW_LOG_FILE, "## Search Results:\n" + resp_text.strip())
        workflow_log_utils.append_to_log(WORKFLOW_LOG_FILE, "__TOOL_EXECUTED__")

    return resp_text.strip()

if __name__ == '__main__':
    print(f"Search MCP started with LOG_FILE: {WORKFLOW_LOG_FILE}", file=sys.stderr) # デバッグ用
    mcp.run(transport="stdio")