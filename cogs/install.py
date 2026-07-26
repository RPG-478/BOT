import sys
import subprocess

def install_psutil():
    try:
        __import__("psutil")
        print("psutil は既にインストールされています。")
    except ImportError:
        print("psutil をインストール中...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
            print("psutil のインストールが完了しました。")
        except subprocess.CalledProcessError as e:
            print(f"エラー: psutil のインストールに失敗しました: {e}")
            sys.exit(1)

if __name__ == "__main__":
    install_psutil()
