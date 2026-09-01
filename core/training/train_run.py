"""Unsloth QLoRA training entrypoint — runs as a subprocess, never inside the HUD server.

Reads a JSON spec path from argv[1] and prints protocol lines for the parent:
    TRAIN_PROGRESS {"step": n, "total": m, "loss": x, "message": "..."}
    TRAIN_DONE <output_dir>
    TRAIN_ERROR <message>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def emit(line: str) -> None:
    print(line, flush=True)


def main() -> None:
    if len(sys.argv) < 2:
        emit("TRAIN_ERROR Missing training config path.")
        return
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = spec["config"]
    try:
        try:
            from unsloth import FastLanguageModel
        except ImportError:
            emit(
                "TRAIN_ERROR The 'unsloth' package is not installed. "
                "Install it with: pip install unsloth"
            )
            return

        from datasets import Dataset
        from transformers import TrainerCallback
        from trl import SFTConfig, SFTTrainer

        emit(
            "TRAIN_PROGRESS "
            + json.dumps(
                {
                    "step": 0,
                    "total": 0,
                    "loss": None,
                    "message": "Loading base model (first run downloads the weights)...",
                }
            )
        )
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=cfg["model"],
            max_seq_length=int(cfg["max_seq"]),
            load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=int(cfg["lora_r"]),
            target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
            lora_alpha=int(cfg["lora_alpha"]),
            lora_dropout=float(cfg["lora_dropout"]),
            bias="none",
            use_gradient_checkpointing="unsloth",
        )

        rows: list[dict] = []
        with Path(spec["dataset"]).open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        if not rows:
            emit("TRAIN_ERROR The dataset is empty.")
            return

        def to_text(example: dict) -> dict:
            return {
                "text": tokenizer.apply_chat_template(
                    example["messages"], tokenize=False, add_generation_prompt=False
                )
            }

        dataset = Dataset.from_list(rows).map(to_text, remove_columns=["messages"])

        class Progress(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                emit(
                    "TRAIN_PROGRESS "
                    + json.dumps(
                        {
                            "step": int(getattr(state, "global_step", 0)),
                            "total": int(getattr(state, "max_steps", 0)),
                            "loss": (logs or {}).get("loss"),
                            "message": "Training...",
                        }
                    )
                )

        output_dir = Path(spec["output_dir"])
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=dataset,
            args=SFTConfig(
                dataset_text_field="text",
                max_seq_length=int(cfg["max_seq"]),
                per_device_train_batch_size=int(cfg["batch_size"]),
                gradient_accumulation_steps=int(cfg["grad_accum"]),
                num_train_epochs=int(cfg["epochs"]),
                learning_rate=float(cfg["learning_rate"]),
                logging_steps=1,
                warmup_ratio=0.05,
                lr_scheduler_type="cosine",
                seed=42,
                report_to="none",
                output_dir=str(output_dir),
            ),
            callbacks=[Progress()],
        )
        trainer.train()
        adapter_dir = Path(spec["output_dir"])
        model.save_pretrained(str(adapter_dir))
        tokenizer.save_pretrained(str(adapter_dir))

        gguf_dir = adapter_dir.parent / "gguf"
        if cfg.get("export_gguf", True):
            emit(
                "TRAIN_PROGRESS "
                + json.dumps(
                    {
                        "step": 0,
                        "total": 0,
                        "loss": None,
                        "message": "Merging LoRA and exporting GGUF (this can take several minutes)...",
                    }
                )
            )
            try:
                try:
                    model.save_pretrained_gguf(
                        str(gguf_dir), tokenizer, quantization_method="q4_k_m"
                    )
                except TypeError:
                    model.save_pretrained_gguf(
                        str(gguf_dir), quantization_method="q4_k_m"
                    )
                produced = sorted(gguf_dir.glob("*.gguf"))
                if not produced:
                    raise RuntimeError("no GGUF file was produced")
                emit(f"TRAIN_GGUF {produced[0]}")
            except Exception as exc:
                emit(
                    "TRAIN_PROGRESS "
                    + json.dumps(
                        {
                            "step": 0,
                            "total": 0,
                            "loss": None,
                            "message": (
                                f"GGUF export failed ({exc.__class__.__name__}); "
                                "the LoRA adapter was still saved."
                            ),
                        }
                    )
                )

        emit(f"TRAIN_DONE {adapter_dir}")
    except Exception as exc:
        emit(f"TRAIN_ERROR {exc.__class__.__name__}: {exc}")


if __name__ == "__main__":
    main()
