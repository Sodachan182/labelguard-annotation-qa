"""LabelGuard Streamlit entry point:  streamlit run app.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from labelguard.ui.app import main

main()
