import os
import json
from pathlib import Path
import google.generativeai as genai
import tweepy
from dotenv import load_dotenv
import sys

# --- 定数設定 ---
GEMINI_MODEL = "gemini-1.5-pro-latest"
POSTED_SLANGS_FILE = Path("posted_slangs.json")

# --- 初期設定 ---
def setup_clients():
    """環境変数を読み込み、APIクライアントを初期化・検証する"""
    load_dotenv()
    
    # APIキーの存在チェック
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    x_api_key = os.getenv("X_API_KEY")
    x_api_key_secret = os.getenv("X_API_KEY_SECRET")
    x_access_token = os.getenv("X_ACCESS_TOKEN")
    x_access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([gemini_api_key, x_api_key, x_api_key_secret, x_access_token, x_access_token_secret]):
        print("エラー: .envファイルに必要なAPIキーが設定されていません。")
        print("必要なキー: GEMINI_API_KEY, X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET")
        sys.exit(1) # エラーでプログラムを終了

    # Geminiクライアントの初期化
    genai.configure(api_key=gemini_api_key)

    # Tweepy (X API v2) Clientの初期化
    try:
        x_client = tweepy.Client(
            consumer_key=x_api_key,
            consumer_secret=x_api_key_secret,
            access_token=x_access_token,
            access_token_secret=x_access_token_secret,
        )
        # 認証情報の検証
        me = x_client.get_me()
        print(f"X APIの認証に成功しました。ユーザー名: @{me.data.username}")
    except Exception as e:
        print(f"エラー: X APIの認証に失敗しました。キーが正しいか、アプリの権限が'Read and Write'になっているか確認してください。")
        print(f"詳細: {e}")
        sys.exit(1)

    return genai, x_client

# --- スラング投稿生成 (Gemini) ---
def generate_slang_post(gemini_client):
    """Gemini APIを使用して、新しいスラングの投稿内容を生成する"""
    print("Gemini APIにリクエストを送り、投稿内容を生成します...")

    # 過去に投稿したスラングを読み込む
    if POSTED_SLANGS_FILE.exists():
        with open(POSTED_SLANGS_FILE, "r", encoding="utf-8") as f:
            try:
                posted_slangs = json.load(f)
            except json.JSONDecodeError:
                posted_slangs = [] # ファイルが空か壊れている場合
    else:
        posted_slangs = []
    
    # 過去の投稿を文字列としてプロンプトに含める
    posted_slangs_str = json.dumps([item.get('slang', '') for item in posted_slangs], ensure_ascii=False)

    prompt = f"""
    あなたはSNSで人気の、フレンドリーな英語学習コンテンツクリエイターです。
    面白くて記憶に残りやすい英語のスラングを1つ選び、その紹介文を作成してください。

    # 要件
    - **絶対に、以下の「過去に投稿したスラング」リストにある単語は使わないでください。**
    - スラング、その日本語の意味、そして使い方がよくわかる簡単な英語の例文と日本語訳を必ず含めてください。
    - 全体の文章は、X(Twitter)の文字数制限（280文字）に収まるように、簡潔にまとめてください。
    - 日本の英語学習者が興味を持つような、比較的新しいスラengや、知っていると面白い表現を選んでください。
    - 文章のトーンは、絵文字(😁🎉など)を少し使って、明るく親しみやすい雰囲気にしてください。
    - 最後に、必ず以下のハッシュタグを付けてください。
      `#英語学習 #スラング #英会話 #今日の英語`

    # 過去に投稿したスラング
    {posted_slangs_str}

    # 出力形式 (必ずこのJSON形式で出力してください)
    {{
      "slang": "生成したスラング (例: 'spill the tea')",
      "post_text": "実際にXに投稿する全文 (スラング、意味、例文、ハッシュタグをすべて含んだもの)"
    }}
    """
    
    generation_config = genai.GenerationConfig(
        temperature=1.2, 
        response_mime_type="application/json",
    )
    model = gemini_client.GenerativeModel(
        GEMINI_MODEL,
        generation_config=generation_config
    )

    try:
        response = model.generate_content(prompt)
        # JSON文字列をPythonの辞書に変換
        generated_content = json.loads(response.text)
        
        # 新しいスラングを過去のリストに追加して保存
        posted_slangs.append(generated_content)
        with open(POSTED_SLANGS_FILE, "w", encoding="utf-8") as f:
            json.dump(posted_slangs, f, indent=2, ensure_ascii=False)
        
        print(f"新しいスラング「{generated_content['slang']}」を生成し、ローカルに保存しました。")
        return generated_content['post_text']

    except Exception as e:
        print(f"エラー: Geminiからの応答の解析、またはファイルの保存に失敗しました。")
        print(f"詳細: {e}")
        # Geminiからの生のレスポンスも表示してみる
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Geminiからの生レスポンス: {response.text}")
        return None

# --- Xへの投稿 ---
def post_to_x(x_client, text_to_post):
    """指定されたテキストをXに投稿する"""
    print("Xへの投稿を実行します...")
    try:
        response = x_client.create_tweet(text=text_to_post)
        print(f"ツイートが正常に投稿されました！ Tweet ID: {response.data['id']}")
        print(f"URL: https://twitter.com/user/status/{response.data['id']}")
    except tweepy.errors.TweepyException as e:
        print(f"エラー: ツイートの投稿に失敗しました。")
        print(f"詳細: {e}")

# --- メイン処理 ---
def main():
    """メインの実行関数"""
    print(f"--- X投稿ボットを開始します ({datetime.datetime.now()}) ---")
    
    gemini_client, x_client = setup_clients()
    
    post_content = generate_slang_post(gemini_client)
    
    if post_content:
        post_to_x(x_client, post_content)
    else:
        print("投稿内容を生成できなかったため、スキップします。")
        
    print("--- 処理を終了します ---")

if __name__ == "__main__":
    # このファイルが直接実行された場合にmain()を呼び出す
    import datetime
    main() 