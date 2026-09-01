import argparse
from pathlib import Path

import json

from core.learning.store import experience_store
from core.memory.store import memory_store


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday-memory")
    parser.add_argument("command", choices=["export", "stats", "clear"])
    args = parser.parse_args()

    if args.command == "stats":
        stats = memory_store.stats()
        experience_store.start()
        learning = experience_store.get_stats()
        experience_store.close()
        print(f"Facts: {stats['facts']} | Episodes: {stats['episodes']} | Rated responses: {learning['rated']}")
        return
    if args.command == "export":
        output = Path("memory-export.json")
        experience_store.start()
        payload = {
            "memory": json.loads(memory_store.export_json()),
            "adaptation": experience_store.export_data(),
        }
        experience_store.close()
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Exported to {output.resolve()}")
        return

    answer = input("Type DELETE ALL to permanently clear FRIDAY's memory: ")
    if answer != "DELETE ALL":
        print("Cancelled.")
        return
    memory_store.clear()
    experience_store.start()
    experience_store.clear()
    experience_store.close()
    print("Memory and adaptive learning data cleared.")


if __name__ == "__main__":
    main()
