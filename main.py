import os
import json
import subprocess
from pathlib import Path
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv
import datetime
import math
import http.server
import socketserver
import threading
from mutagen.mp3 import MP3

# --- 定数設定 ---
# APIモデル設定 (後から変更しやすいように)
GEMINI_MODEL = "gemini-2.5-pro" 
TTS_MODEL = "gpt-4o-mini-tts"                
TTS_VOICE = "ash"                 
# ファイルパス設定
SCRIPTS_FILE = Path("scripts.json")
AUDIO_DIR = Path("audio")
VIDEO_DIR = Path("videos")
REMOTION_PROJECT_DIR = Path("shorts")

# --- 初期設定 ---
def setup_environment():
    """環境変数の読み込みとAPIクライアントの初期化"""
    load_dotenv()
    # APIキーが設定されているか確認
    if not os.getenv("GEMINI_API_KEY") or not os.getenv("OPENAI_API_KEY"):
        raise ValueError("APIキーが.envファイルに設定されていません。")
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def create_directories():
    """音声・動画保存用ディレクトリを作成"""
    AUDIO_DIR.mkdir(exist_ok=True)
    VIDEO_DIR.mkdir(exist_ok=True)

# --- スクリプト生成 (Gemini) ---
def generate_script_with_gemini(is_first_time=False):
    """Gemini APIを使用して動画のスクリプトを生成し、JSONファイルに保存する"""
    print("Gemini APIにリクエストを送り、スクリプトを生成します...")

    # 既存のスクリプトを読み込む
    if SCRIPTS_FILE.exists() and SCRIPTS_FILE.stat().st_size > 0:
        with open(SCRIPTS_FILE, "r", encoding="utf-8") as f:
            scripts_data = json.load(f)
    else:
        scripts_data = []
    
    existing_scripts_str = json.dumps(scripts_data, indent=2, ensure_ascii=False)

    # 初回は3つ、それ以降は10個生成する
    num_to_generate = 1 if is_first_time else 10
    print(f"{num_to_generate}個のユニークなスクリプトを一度に生成します。")

    # Geminiへのプロンプトを更新
    prompt = f"""
    あなたはSNSでバズる短い英語の動画コンテンツのスクリプト作家です。
    以下の要件に従って、新しいスクリプトを **{num_to_generate}個** 作成してください。

    # 最重要要件
    - **生成する {num_to_generate}個 のスクリプトは、互いに全く異なる、ユニークなトピックにしてください。**
    - 以下の「過去に生成したスクリプト」とも内容が重複しないようにしてください。(過去に生成したスクリプトのスタイルは、手本ではないので、参考にする必要はありません。)

    # その他の要件
    - 各スクリプトは、90単語程度の英語の文章と、その自然な日本語訳で構成してください。
    - 英語のレベルはCEFR B1レベル（初級～中級者向け）にしてください。
    - 語り手は、男性を想定してください。
    - スクリプトの最初の数語は、難しい単語を使わず、かつ、視聴者に「どういう話？」と疑問を持たせるフックとなるようなものにしてください。
    - トピックは、人々がコメントしたくなるような、物議を醸しやすく、意見が分かれやすいものを選んでください。必ずしも英語圏の人ではなく日本人でも共感できるものや、世界共通の話題、恋愛の話題などが望ましいです。
    - 各スクリプトの最後には、予想を裏切る、非常に面白いジョークのオチをつけてください。

    # 過去に生成したスクリプト
    {existing_scripts_str}

    # 出力形式
    - **必ず、{num_to_generate}個のスクリプト全体を単一のJSON配列 `[]` として出力してください。**
    - 配列の各要素は、"english_script" と "japanese_translation" のキーを持つJSONオブジェクトにしてください。
    [
      {{
        "english_script": "1つ目の英語スクリプト",
        "japanese_translation": "1つ目の日本語訳"
      }},
      {{
        "english_script": "2つ目の英語スクリプト",
        "japanese_translation": "2つ目の日本語訳"
      }},
      ...
    ]
    """
    
    generation_config = genai.GenerationConfig(
        temperature=1.8, 
        response_mime_type="application/json",
    )
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config=generation_config
    )

    try:
        print(f"Geminiにリクエスト中 (ストリーミング)...")
        response = model.generate_content(prompt, stream=True)
        
        full_response_text = ""
        for chunk in response:
            full_response_text += chunk.text

        # 全てのチャンクを結合してからJSONとしてパース
        new_scripts = json.loads(full_response_text)
        
        if not isinstance(new_scripts, list):
             raise json.JSONDecodeError("応答がJSON配列ではありません。", full_response_text, 0)

    except (json.JSONDecodeError, AttributeError) as e:
        print(f"エラー: Geminiからの応答の解析に失敗しました。応答: {full_response_text}, エラー: {e}")
        return []
    except Exception as e:
        print(f"予期せぬストリーミングエラーが発生しました: {e}")
        return []


    # 新しいスクリプトを既存のリストに追加して保存
    scripts_data.extend(new_scripts)
    with open(SCRIPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(scripts_data, f, indent=2, ensure_ascii=False)
        
    print(f"{len(new_scripts)}個の新しいスクリプトを {SCRIPTS_FILE} に保存しました。")
    return new_scripts

# --- 音声生成 (OpenAI TTS) ---
def generate_audio_with_openai(client, scripts):
    """OpenAI TTS APIを使用して音声を生成する"""
    print("OpenAI TTS APIを使用して音声を生成します...")
    audio_paths = []
    # 複数のファイルを同時に生成しても名前が被らないようにベースのタイムスタンプを取得
    base_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for i, script in enumerate(scripts):
        script_text = script.get("english_script")
        if not script_text:
            print(f"警告: スクリプト {i+1} に 'english_script' が見つかりません。")
            continue
            
        # タイムスタンプとインデックスでファイル名を一意にする (例: script_20231027_153000_0.mp3)
        audio_file_path = AUDIO_DIR / f"script_{base_timestamp}_{i}.mp3"

        try:
            # DeprecationWarningを解消するため、with_streaming_responseを使用
            with client.audio.speech.with_streaming_response.create(
                model=TTS_MODEL,
                voice=TTS_VOICE,
                input=script_text
            ) as response:
                response.stream_to_file(audio_file_path)
            
            audio_paths.append(audio_file_path)
            print(f"音声を {audio_file_path} に保存しました。")
        except Exception as e:
            print(f"エラー: 音声ファイル {audio_file_path} の生成に失敗しました。エラー: {e}")

    return audio_paths

# --- 動画生成 (Remotion) ---
def render_video_with_remotion(props, audio_path):
    """Remotion CLIを呼び出して動画をレンダリングする"""
    print(f"Remotionで動画をレンダリングします... スクリプト: {props['scriptText'][:30]}...")
    
    # 出力ファイルパス
    # ファイル名にスクリプトのタイムスタンプ部分を流用する
    timestamp_part = Path(audio_path).stem.replace('script_', '')
    output_video_path = VIDEO_DIR / f"toremock_short_{timestamp_part}.mp4"

    # Windows環境でのnpxのフルパスを指定。
    # これで環境変数PATHに依存せず、npxを直接実行できる。
    # 注: Node.jsのインストール場所が異なる場合は、このパスを修正してください。
    npx_path = "C:\\Program Files\\nodejs\\npx.cmd"

    # コマンドの構築
    # npx remotion render <Composition-ID> <output-path> --props '{...}'
    command = [
        npx_path,
        "remotion",
        "render",
        "MainVideo",  # RemotionプロジェクトのComposition ID
        str(output_video_path),
        "--props",
        json.dumps(props)
    ]

    print(f"実行コマンド: {' '.join(command)}")

    # Remotionコマンドを実行
    try:
        # cwdでremotionプロジェクトのディレクトリに移動してコマンドを実行
        # encoding='utf-8'とerrors='ignore'を追加して、Windowsでの文字化けエラーを回避
        subprocess.run(command, check=True, cwd=REMOTION_PROJECT_DIR, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        print(f"動画を {output_video_path} に正常にレンダリングしました。")
    except FileNotFoundError:
        print(f"エラー: '{npx_path}' が見つかりません。Node.jsのインストール場所を確認してください。")
        print(f"また、'{REMOTION_PROJECT_DIR}' ディレクトリで 'npm install' を実行してください。")
    except subprocess.CalledProcessError as e:
        print(f"エラー: Remotionのレンダリングに失敗しました。")
        print(f"リターンコード: {e.returncode}")
        print(f"標準出力: {e.stdout}")
        print(f"標準エラー出力: {e.stderr}")
        print("---")
        print("Remotionプロジェクトが正しくセットアップされているか確認してください。")
        print(f"1. '{REMOTION_PROJECT_DIR}' ディレクトリは存在しますか？")
        print(f"2. 'npm install' は実行しましたか？")
        print(f"3. 'src/Root.tsx' に 'MainVideo' というComposition IDのコンポーネントはありますか？")


# --- メイン処理 ---
def main():
    """メインの実行関数"""
    # 一時的なローカルWebサーバーをセットアップ
    PORT = 8000
    Handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), Handler)
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True # メインスレッドが終了したらサーバーも終了する

    try:
        print(f"一時的なローカルサーバーを http://localhost:{PORT} で起動します...")
        server_thread.start()

        openai_client = setup_environment()
        create_directories()

        # 初めて実行するかどうかを判定（scripts.jsonの有無）
        is_first_time = not SCRIPTS_FILE.exists() or os.path.getsize(SCRIPTS_FILE) == 0

        # 1. スクリプト生成
        new_scripts = generate_script_with_gemini(is_first_time=is_first_time)
        if not new_scripts:
            print("新しいスクリプトが生成されなかったため、処理を終了します。")
            return

        # 2. 音声生成
        # 生成されたすべての新しいスクリプトに対して音声を生成する
        audio_paths = generate_audio_with_openai(openai_client, new_scripts)

        if not audio_paths:
            print("音声ファイルが生成されなかったため、処理を終了します。")
            return
            
        # 3. 動画生成
        # 生成された各スクリプトと音声で動画をレンダリングする
        print("\n--- 動画生成を開始します ---")
        for script, audio_path in zip(new_scripts, audio_paths):
            # Python側で音声の長さを取得
            try:
                audio_duration_seconds = MP3(audio_path).info.length
                # Remotionに渡す動画の長さをフレーム単位で計算
                # 音声の長さに終了マージンとして1秒を追加（開始オフセットは削除）
                duration_in_frames = math.ceil((audio_duration_seconds + 1.0) * 60) # 60 FPS
                
                # propsにdurationInFramesを追加
                props = {
                    "title": "TOEIC 600点 のシャドーイング",
                    "subtitle": "最後まで遅れずに読めたらすごい",
                    "scriptText": script["english_script"],
                    # audioUrlをローカルサーバーのURLに変更
                    "audioUrl": f"http://localhost:{PORT}/{audio_path.as_posix()}",
                    "durationInFrames": duration_in_frames
                }
                render_video_with_remotion(props, audio_path)

            except Exception as e:
                print(f"エラー: 音声ファイル {audio_path} の長さの取得または動画レンダリングに失敗しました。エラー: {e}")


        print(f"\nすべての処理が完了しました。{len(audio_paths)}個の動画ファイルが videos フォルダに作成されたはずです。")

    except ValueError as e:
        print(f"設定エラー: {e}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
    finally:
        # サーバーをシャットダウン
        print("一時的なローカルサーバーを停止します...")
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    main() 