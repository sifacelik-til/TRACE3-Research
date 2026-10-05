import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import src.cdp_text_clustering.benchmark_cdp_action_taxonomy as benchmark


class EncoderTests(unittest.TestCase):
    def encode_with(self, model, key="jina_v3"):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "span_records.jsonl.gz").write_bytes(b"sample")
            with (
                patch.object(benchmark, "np", np),
                patch.object(benchmark, "resolve_model", return_value=(output, "revision")),
                patch("sentence_transformers.SentenceTransformer", return_value=model) as constructor,
            ):
                benchmark.encode_model(
                    key, [{"clustering_text": "Install renewable power"}], output,
                    batch_size=1, device="cpu", offline=True,
                )
            state = json.loads((output / "encoders" / key / "manifest.json").read_text())
            return constructor.call_args.kwargs, state

    def test_jina_uses_original_checkpoint_and_forwards_separation(self):
        class Model:
            module_kwargs = {"transformer": ["task"]}

            def encode(self, texts, **kwargs):
                self.task = kwargs.get("task")
                return np.array([[1.0, 0.0]])

        model = Model()
        kwargs, state = self.encode_with(model)
        self.assertEqual(state["model_id"], "jinaai/jina-embeddings-v3")
        self.assertTrue(kwargs["trust_remote_code"])
        self.assertTrue(kwargs["local_files_only"])
        self.assertEqual(model.task, "separation")
        self.assertEqual(state["task"], "separation")

    def test_explicit_task_parameter_remains_supported(self):
        class Model:
            def encode(self, texts, task=None, **kwargs):
                self.task = task
                return np.array([[1.0, 0.0]])

        model = Model()
        _, state = self.encode_with(model)
        self.assertEqual(model.task, "separation")
        self.assertEqual(state["task"], "separation")

    def test_kwargs_without_task_routing_are_rejected(self):
        class Model:
            module_kwargs = {"transformer": []}

            def encode(self, texts, **kwargs):
                raise AssertionError("Unsupported task must fail before encoding")

        with self.assertRaisesRegex(RuntimeError, "requires the 'separation' embedding task"):
            self.encode_with(Model())

    def test_non_task_encoder_is_unchanged(self):
        class Model:
            def encode(self, texts, **kwargs):
                self.kwargs = kwargs
                return np.array([[1.0, 0.0]])

        model = Model()
        kwargs, state = self.encode_with(model, "minilm")
        self.assertFalse(kwargs["trust_remote_code"])
        self.assertNotIn("task", model.kwargs)
        self.assertEqual(state["task"], "none")


if __name__ == "__main__":
    unittest.main()
