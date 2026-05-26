import os
import sys
# Добавляем путь к исходному коду, чтобы Sphinx мог импортировать модули для анализа
sys.path.insert(0, os.path.abspath('../src'))

project = 'FlakyDetector'
copyright = '2026, Research Team'
author = 'Research Team'
release = '0.1.0'

# Подключаем расширения для автогенерации, поддержки Google-стиля докстрингов и Markdown
extensions = [
    'sphinx.ext.autodoc',      # Автогенерация документации из докстрингов
    'sphinx.ext.napoleon',     # Поддержка Google и NumPy стилей docstrings
    'sphinx.ext.viewcode',     # Добавление ссылок на исходный код в документации
    'sphinx.ext.intersphinx',  # Ссылки на документацию внешних библиотек
    'myst_parser',             # Парсер для поддержки файлов .md (Markdown)
]

# Настройки парсера Markdown для поддержки таблиц и блоков внимания (нотификаций)
myst_enable_extensions = [
    "colon_fence",
    "table",
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# Тема оформления и ее кастомизация
html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'collapse_navigation': False,
    'display_version': True,
    'navigation_depth': 4,
}

html_static_path = ['_static']

# Настройки автодокументации: сохранять порядок кода, показывать типы
autodoc_member_order = 'bysource'
autoclass_content = 'both'
autodoc_typehints = 'description'


autodoc_mock_imports = [
    "catboost",
    "tree_sitter",
    "tree_sitter_python",
    "cupy",
    "jax",
    "openai",
    "anthropic",
    "plotly",
    "kaleido"
]
