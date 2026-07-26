import sys
import subprocess

def install_psutil():
    try:
        __import__("psutil")
        print("psutil は既にインストールされています。")
    except ImportError:
        print("psutil をインストール中...")
        cmd = [sys.executable, "-m", "pip", "install", "psutil"]
        try:
            subprocess.check_call(cmd)
            print("psutil のインストールが完了しました。")
        except subprocess.CalledProcessError:
            try:
                print("システム制限を回避して再試行中...")
                subprocess.check_call(cmd + ["--break-system-packages"])
                print("psutil のインストールが完了しました。")
            except subprocess.CalledProcessError as e:
                print(f"エラー: psutil のインストールに失敗しました: {e}")
                sys.exit(1)

if __name__ == "__main__":
    install_psutil()
