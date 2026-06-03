"""LLM Анализатор Flaky тестов (Локальная Ollama)."""
from __future__ import annotations

import json
from pathlib import Path
from openai import OpenAI

SYSTEM_PROMPT = """
You are a Principal QA Automation Engineer specializing in Python's pytest, asyncio, and race conditions.
Your task is to analyze flaky tests and provide a scientific diagnosis.
You MUST respond ONLY with a valid JSON object matching this exact schema:
{
  "root_cause_category": "string (e.g., 'Race Condition', 'State Leakage', 'Non-deterministic Mock', 'Timing Dependency')",
  "explanation": "string (Detailed explanation of WHY this test fails intermittently)",
  "fix_strategy": "string (How to fix it architecturally)",
  "fixed_code": "string (The complete rewritten test function that is deterministic)"
}
"""

USER_TEMPLATE = """
Analyze this flaky test. It failed {fail_count} times out of {total_count} runs (Flakiness Rate: {rate}%).
--- SOURCE CODE ---
```python
{source_code}  --- SAMPLE TRACEBACKS ---
{tracebacks_formatted}
Provide your analysis as a JSON object.
"""


def format_tracebacks(tracebacks: list[str]) -> str:
    if not tracebacks:
        return "No tracebacks available."
    unique_tbs = list(set(tracebacks))
    return "\n---\n".join([f"text\n{tb}\n" for tb in unique_tbs[:2]])


def main():
    input_path = Path("data/processed/flaky_dataset.jsonl")
    output_path = Path("data/processed/llm_analysis_results.jsonl")

    if not input_path.exists():
        print(f"File {input_path} not found.")
        return

    # Подключаемся к ЛОКАЛЬНОЙ Ollama (не нужен интернет и ключи)
    client = OpenAI(
        api_key="ollama",  # Заглушка, Ollama ключей не требует
        base_url="http://localhost:11434/v1"
    )

    records = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    print(f"🧠 Отправляем {len(records)} записей в локальную Ollama (qwen2.5-coder:7b)...")

    with open(output_path, "w", encoding="utf-8") as out_f:
        for record in records:
            user_prompt = USER_TEMPLATE.format(
                fail_count=record["runs_total"] - (record["runs_total"] * record["flakiness_rate_percent"] // 100),
                total_count=record["runs_total"],
                rate=record["flakiness_rate_percent"],
                source_code=record["source_code"],
                tracebacks_formatted=format_tracebacks(record["sample_tracebacks"])
            )

            response = client.chat.completions.create(
                model="qwen2.5-coder:7b",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )

            llm_result = json.loads(response.choices[0].message.content)

            final_record = {
                "original_nodeid": record["nodeid"],
                "original_flakiness_rate": record["flakiness_rate_percent"],
                "llm_analysis": llm_result
            }

            out_f.write(json.dumps(final_record, ensure_ascii=False) + "\n")
            print(f"✅ Проанализирован: {record['nodeid']}")

    print(f"💾 Результаты сохранены в {output_path}")


if __name__ == "__main__":
    main()