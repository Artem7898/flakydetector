"""The v0.1 45D hybrid pipeline is retired: it leaked current outcome into features.

Use the same reviewed, provenance-aware export as extract_dataset.py.
No model is trained implicitly by dataset extraction.
"""

from extract_dataset import main

if __name__ == "__main__":
    main()
