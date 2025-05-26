import bootstrap_path #インポートするだけでOK
import sys
# import workflow_log_utils # .mdログへの書き込みを行わないため不要に
import urllib.parse
import requests
from bs4 import BeautifulSoup, Tag
from mcp.server.fastmcp import FastMCP
import time # 待機用
print(f"DEBUG: {__file__} が引数 {sys.argv} で開始されました．", file=sys.stderr)

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
             検索結果がない場合はその旨を伝えるメッセージを返します．

    Raises:
        requests.exceptions.RequestException: 検索リクエストが失敗した場合．
        AttributeError: HTML構造が期待どおりでない場合．
    """
    resp_text = ""
    num_iterations = (max_results + 9) // 10 
    num_iterations = min(num_iterations, 5) 

    for i in range(num_iterations):
        begin_count = i * 10 + 1
        search_url = f"https://search.yahoo.co.jp/search?p={urllib.parse.quote_plus(keyword)}&qrw=0&b={begin_count}"
        print(f"DEBUG: Searching URL: {search_url}", file=sys.stderr) # デバッグ用

        try:
            response = requests.get(search_url, timeout=10) 
            response.raise_for_status() 
            res_html = BeautifulSoup(response.text, "lxml")
            search_items = res_html.select('div#web li')

            if not search_items:
                if i == 0: 
                    # 最初のページで結果がない場合のみメッセージを返す (ループは継続しない)
                    # return f"キーワード '{keyword}' の検索結果は見つかりませんでした．" # ここでreturnすると複数ページ検索できない
                    print(f"DEBUG: No search results on page {i+1} for '{keyword}'", file=sys.stderr)
                else: 
                    print(f"DEBUG: No more search results on page {i+1} for '{keyword}'", file=sys.stderr)
                    break # 2ページ目以降で結果がなくなったらループを抜ける

            for item_idx, item in enumerate(search_items):
                link_tag = item.select_one('a')
                description_tag = item.select_one('div') # より汎用的なセレクタに変更検討

                if link_tag and 'href' in link_tag.attrs:
                    title = link_tag.get_text(strip=True)
                    url = link_tag.attrs['href']
                    
                    # 説明文の取得を改善 (より多くのケースに対応するため)
                    description_parts = []
                    if description_tag:
                        # div直下のテキストノードや、spanなどの子要素のテキストを取得
                        for content_part in description_tag.contents:
                            if isinstance(content_part, str):
                                cleaned_part = content_part.strip()
                                if cleaned_part:
                                    description_parts.append(cleaned_part)
                            elif isinstance(content_part, Tag): # Tagオブジェクトの場合
                                cleaned_part = content_part.get_text(strip=True)
                                if cleaned_part:
                                    description_parts.append(cleaned_part)
                    
                    description = " ".join(description_parts) if description_parts else "説明文なし"
                    
                    # 簡単な広告フィルタリング（例：URLに "ad." や "r.auctions.yahoo.co.jp" などが含まれる場合）
                    # より高度なフィルタリングが必要な場合がある
                    if "r.auctions.yahoo.co.jp" in url or "ad." in url or "sponsored" in title.lower():
                        print(f"DEBUG: Skipping ad-like result: {title}", file=sys.stderr)
                        continue

                    resp_text += f"# [{title}]({url})\n"
                    resp_text += f"{description}\n\n"
                    
                    # max_results に達したら早期終了
                    if len(resp_text.split("\n\n")) -1 >= max_results: # -1 は最後の空行分
                        print(f"DEBUG: Reached max_results ({max_results}). Stopping search.", file=sys.stderr)
                        break 
            if len(resp_text.split("\n\n")) -1 >= max_results:
                break


        except requests.exceptions.RequestException as e:
            if i == 0: 
                print(f"検索リクエスト中にエラーが発生しました: {e}", file=sys.stderr)
                return f"検索リクエスト中にエラーが発生しました: {e}"
            else: 
                print(f"Warning: 検索リクエスト中にエラー (ページ {i+1}): {e}", file=sys.stderr)
                break 
        except AttributeError as e_attr:
            if i == 0:
                print(f"エラー: Yahoo検索のHTML構造が変わった可能性があります: {e_attr}", file=sys.stderr)
                return f"エラー: Yahoo検索のHTML構造が変わった可能性があります。"
            else:
                print(f"Warning: HTML構造解析エラー (ページ {i+1}): {e_attr}", file=sys.stderr)
                break
        except Exception as e_generic:
            if i == 0:
                print(f"検索中に予期せぬエラーが発生しました: {e_generic}", file=sys.stderr)
                return f"検索中に予期せぬエラーが発生しました: {e_generic}"
            else:
                print(f"Warning: 検索中の予期せぬエラー (ページ {i+1}): {e_generic}", file=sys.stderr)
                break
        
        time.sleep(0.5) # 連続リクエストを避けるための短い待機

    if not resp_text.strip(): # strip() を追加して空行のみの場合も判定
        return f"キーワード '{keyword}' の検索結果は見つかりませんでした（またはフィルタリングされました）。"

    return resp_text.strip()

if __name__ == '__main__':
    print(f"Search MCP (search_mcp.py) 開始．", file=sys.stderr)
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        print(f"Search MCP ランタイムエラー: {e}", file=sys.stderr)
        sys.exit(1)
