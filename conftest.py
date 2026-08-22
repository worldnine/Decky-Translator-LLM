# リポジトリルートを sys.path に追加し、PYTHONPATH 指定なしで pytest tests/ が動くようにする
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
