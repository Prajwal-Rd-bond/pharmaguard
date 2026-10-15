import os
import json
import tempfile
import unittest

from app.eval.train_qlora import (
    format_llama3_prompt,
    parse_instruction_record,
    load_and_validate_dataset,
    estimate_qlora_params,
    get_peft_adapter_config,
    run_training_pipeline,
)


class TestQLoRATraining(unittest.TestCase):
    def test_parse_alpaca_record(self):
        record = {
            "instruction": "Extract suspect drug and adverse events.",
            "input": "Patient took Lisinopril 20mg and developed severe angioedema.",
            "output": '{"drug": "Lisinopril", "adverse_events": ["angioedema"]}',
        }
        parsed = parse_instruction_record(record)
        self.assertIsNotNone(parsed)
        self.assertIn("Lisinopril 20mg", parsed["user"])
        self.assertEqual(parsed["assistant"], record["output"])

    def test_parse_sharegpt_record(self):
        record = {
            "messages": [
                {"role": "system", "content": "Custom PV System"},
                {"role": "user", "content": "Extract symptoms"},
                {"role": "assistant", "content": "Anaphylaxis"},
            ]
        }
        parsed = parse_instruction_record(record)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["system"], "Custom PV System")
        self.assertEqual(parsed["user"], "Extract symptoms")
        self.assertEqual(parsed["assistant"], "Anaphylaxis")

    def test_format_llama3_prompt(self):
        formatted = format_llama3_prompt(
            system_prompt="PV Assistant",
            user_prompt="Report text",
            assistant_prompt="Extracted entities",
        )
        self.assertIn("<|begin_of_text|>", formatted)
        self.assertIn("<|start_header_id|>system<|end_header_id|>\n\nPV Assistant<|eot_id|>", formatted)
        self.assertIn("<|start_header_id|>user<|end_header_id|>\n\nReport text<|eot_id|>", formatted)
        self.assertIn("<|start_header_id|>assistant<|end_header_id|>\n\nExtracted entities<|eot_id|>", formatted)

    def test_estimate_qlora_params(self):
        stats = estimate_qlora_params(base_model_params=8_000_000_000, lora_r=16)
        self.assertGreater(stats["trainable_params"], 0)
        self.assertLess(stats["trainable_percent"], 1.0)  # LoRA should be < 1%
        self.assertGreater(stats["trainable_percent"], 0.05)
        self.assertLess(stats["qlora_4bit_memory_gb"], 10.0)  # Fits in 16GB consumer GPU
        self.assertGreater(stats["fp32_memory_gb"], 25.0)  # FP32 needs datacenter GPU
        self.assertGreater(stats["memory_saving_percent"], 70.0)

    def test_peft_adapter_config(self):
        config = get_peft_adapter_config(
            model_id="mistralai/Mistral-7B-Instruct-v0.2",
            lora_r=32,
            lora_alpha=64,
            lora_dropout=0.1,
        )
        self.assertEqual(config["base_model_name_or_path"], "mistralai/Mistral-7B-Instruct-v0.2")
        self.assertEqual(config["peft_type"], "LORA")
        self.assertEqual(config["task_type"], "CAUSAL_LM")
        self.assertEqual(config["r"], 32)
        self.assertEqual(config["lora_alpha"], 64)
        self.assertIn("q_proj", config["target_modules"])

    def test_end_to_end_dry_run_training(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jsonl_path = os.path.join(tmp_dir, "test_instructions.jsonl")
            output_dir = os.path.join(tmp_dir, "adapters_out")

            sample_data = [
                {
                    "instruction": "Identify drug and reaction",
                    "input": "Patient reported acute pancreatitis after taking Sitagliptin.",
                    "output": '{"drug": "Sitagliptin", "reaction": "acute pancreatitis"}',
                },
                {
                    "instruction": "Classify seriousness",
                    "input": "Patient hospitalized with Stevens-Johnson syndrome.",
                    "output": '{"serious": true, "criteria": ["hospitalization"]}',
                },
            ]

            with open(jsonl_path, "w", encoding="utf-8") as f:
                for item in sample_data:
                    f.write(json.dumps(item) + "\n")

            summary = run_training_pipeline(
                data_path=jsonl_path,
                model_id="meta-llama/Meta-Llama-3-8B-Instruct",
                output_dir=output_dir,
                epochs=2,
                batch_size=1,
                dry_run=True,
            )

            self.assertIn(summary["status"], ["completed", "dry_run_verified"])
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["dataset_samples"], 2)
            self.assertEqual(summary["epochs"], 2)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "adapter_config.json")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "run_summary.json")))

            with open(os.path.join(output_dir, "adapter_config.json")) as f:
                saved_cfg = json.load(f)
                self.assertEqual(saved_cfg["peft_type"], "LORA")
                self.assertEqual(saved_cfg["r"], 16)


if __name__ == "__main__":
    unittest.main()
