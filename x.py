import os
import json
from pathlib import Path
import google.generativeai as genai
import tweepy
from dotenv import load_dotenv
import sys

# --- 定数設定 ---
GEMINI_MODEL = "gemini-2.5-flash-lite-preview-06-17"
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

# --- 投稿済みアイテムの読み書きユーティリティ ---

def load_posted_items():
    """posted_slangs.json を読み込んでリストを返す。ファイルが無ければ空リスト。"""
    if POSTED_SLANGS_FILE.exists():
        try:
            with open(POSTED_SLANGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            # ファイルが壊れていた場合はバックアップして新しく作る
            POSTED_SLANGS_FILE.rename(POSTED_SLANGS_FILE.with_suffix(".bak"))
    return []


def save_posted_items(items_list):
    """投稿済みアイテムのリストを JSON ファイルに保存する"""
    with open(POSTED_SLANGS_FILE, "w", encoding="utf-8") as f:
        json.dump(items_list, f, ensure_ascii=False, indent=2)

# --- 英語表現ツイート生成 (Gemini) ---

def generate_tweet_content(existing_items):
    """Gemini API を呼び出し、ツイート本文と新しい表現を返す"""
    print("Gemini APIにリクエストを送り、ツイート内容を生成します...")

    existing_items_str = ", ".join(existing_items) if existing_items else "なし"
    
    prompt = f"""
    あなたは、ネイティブが使う自然な英語表現を紹介する、SNSで大人気のインフルエンサーです。
    以下の要件とフォーマットに従って、新しいツイートを作成してください。

    # 最重要要件
    - 以下の「過去に投稿した表現」とは絶対に重複しない、新しい英語の「言い回し」や「フレーズ」を1つだけ選んでください。
      過去に投稿した表現: {existing_items_str}
    - 生成する内容は、以下の「出力フォーマット」を厳格に守ってください。見出しや絵文字、改行も完全に同じにしてください。

    # その他の要件
    - 日本の英語学習者が「へぇ、そう言うんだ！」「使ってみたい！」と感じるような、面白くて実用的な表現を選んでください。
    - 解説は、単なる直訳ではなく、どんな場面で、どういう気持ちで使うのかが伝わるように、生き生きとした言葉で記述してください。
    - 例文は、AとBの短い会話形式にしてください。
    - 全体を通して、親しみやすく、少しユーモアのあるトーンで書いてください。
    - "[]"は出力に含めないでください。

    # 出力フォーマット (この形式を厳守してください)
    【今日のネイティブフレーズ】
    [英語の表現]

    [表現が使われる状況や意味を一言で]という時にぴったりの表現です！

    👉 [具体的な状況や感情、どんな人が使うかなどの詳しい解説]
    👉 [もう一歩踏み込んだニュアンスや、似ている表現との違いなど]

    📢例文
    A: "[例文でのセリフA]"
    B: "[例文でのセリフB]"

    [その表現の由来や、使う際のちょっとした注意点など、読者が「へぇ」と思うような短い情報]

    #英語学習 #英会話 #TOEIC #TOEFL
    """

    generation_config = genai.GenerationConfig(
        temperature=1.0,
        max_output_tokens=1024,
    )
    safety_settings = [
        {
            "category": "HARM_CATEGORY_HARASSMENT",
            "threshold": "BLOCK_NONE"
        },
        {
            "category": "HARM_CATEGORY_HATE_SPEECH",
            "threshold": "BLOCK_NONE"
        },
        {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "threshold": "BLOCK_NONE"
        },
        {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
            "threshold": "BLOCK_NONE"
        }
    ]
    
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config=generation_config,
        safety_settings=safety_settings,
    )

    try:
        response = model.generate_content(prompt)
        if not response.parts:
            print(f"Geminiからの応答がブロックされました。Feedback: {response.prompt_feedback}")
            return None, None
            
        tweet_text = response.text.strip().replace("`", "")
        
        # 生成されたテキストから新しい表現を抽出
        lines = tweet_text.split('\n')
        new_item = None
        if len(lines) > 1 and "【今日のネイティブフレーズ】" in lines[0]:
            new_item = lines[1].strip()
        return tweet_text, new_item

    except Exception as e:
        print(f"エラー: Geminiからの応答の取得に失敗しました。エラー: {e}")
        return None, None

# --- Xへの投稿 ---

def post_to_x(x_client, text_to_post):
    """指定されたテキストをXに投稿し、成功可否をboolで返す"""
    print("Xへの投稿を実行します...")
    try:
        response = x_client.create_tweet(text=text_to_post)
        tweet_id = response.data.get("id") if response and response.data else None
        if tweet_id:
            print(f"ツイートが正常に投稿されました！ Tweet ID: {tweet_id}")
            print(f"URL: https://twitter.com/user/status/{tweet_id}")
            return True
    except tweepy.errors.TweepyException as e:
        print("エラー: ツイートの投稿に失敗しました。")
        print(f"詳細: {e}")
    return False

# --- メイン処理 ---

def main():
    """メインの実行関数"""
    print("--- 処理を開始します ---")
    try:
        _genai_module, x_client = setup_clients()

        # 1. 過去に投稿したアイテムを読み込む
        existing_items = load_posted_items()

        # 2. 新しい表現でツイートを生成
        tweet_text, new_item = generate_tweet_content(existing_items)
        if not tweet_text:
            print("ツイート内容が生成されませんでした。処理を終了します。")
            return

        # 3. Xに投稿
        if post_to_x(x_client, tweet_text):
            # 投稿成功
            if new_item:
                existing_items.append(new_item)
                save_posted_items(existing_items)
                print(f"表現 '{new_item}' を履歴に追加しました。")
            else:
                print("警告: 新しい表現名が取得できなかったため、履歴は更新されませんでした。")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
    finally:
        print("--- 処理を終了します ---")

if __name__ == "__main__":
    # このファイルが直接実行された場合にmain()を呼び出す
    import datetime
    main() 