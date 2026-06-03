"""
RAG Pipeline: Векторизация LLM-анализов с помощью ChromaDB.
Позволяет искать тесты с семантически похожими причинами флакинесса.
"""
from __future__ import annotations

import json
from pathlib import Path

import chromadb

# Путь к нашим результатам LLM
JSONL_PATH = Path("data/processed/llm_analysis_results.jsonl")
# Папка для хранения векторной БД на диске (персистентность)
DB_DIR = Path("data/vector_db")


def main():
    if not JSONL_PATH.exists():
        print(f"❌ Сначала запусти llm_analyze.py, не найден {JSONL_PATH}")
        return

    # Инициализируем клиент ChromaDB (сохраняет данные на диск)
    client = chromadb.PersistentClient(path=str(DB_DIR))

    # Получаем или создаем коллекцию (по умолчанию использует sentence-transformers)
    collection = client.get_or_create_collection(name="flaky_analyses")

    # Очищаем коллекцию перед пересборкой (для чистоты эксперимента)
    if collection.count() > 0:
        print("🧹 Очищаем старые векторы...")
        client.delete_collection("flaky_analyses")
        collection = client.get_or_create_collection(name="flaky_analyses")

    records = [json.loads(line) for line in JSONL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

    print(f"🧠 Векторизуем {len(records)} записей...")

    for rec in records:
        analysis = rec["llm_analysis"]
        # Склеиваем категорию и объяснение для богатого контекста
        text_to_embed = f"Category: {analysis['root_cause_category']}\nExplanation: {analysis['explanation']}"

        collection.add(
            ids=[rec["original_nodeid"]],  # Уникальный ID теста
            documents=[text_to_embed],  # Текст для векторизации
            metadatas=[{
                "flakiness_rate": rec["original_flakiness_rate"],
                "fix_strategy": analysis["fix_strategy"]
            }]
        )

    print(f"✅ Сохранено {collection.count()} векторов в {DB_DIR}")

    # --- ДЕМОНСТРАЦИЯ: Семантический поиск ---
    print("\n🔍 Тестовый запрос: 'Ищем тесты с проблемами состояния и утечками памяти'...")

    results = collection.query(
        query_texts=["Проблемы с общим состоянием, утечки памяти, мутабельные объекты"],
        n_results=2
    )

    print("\nНайдены похожие тесты:")
    for i, (doc, metadata, distance) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
    )):
        print(f"\n--- Результат {i + 1} (Сходство: {1 - distance:.2%}) ---")
        print(f"Flakiness Rate: {metadata['flakiness_rate']}%")
        print(f"Анализ LLM:\n{doc}\n")


if __name__ == "__main__":
    main()