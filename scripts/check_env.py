"""Exercise course imports, representative APIs and the registered Jupyter kernel."""

import argparse
import ast
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = {
    "numpy", "scipy", "sklearn", "h5py", "matplotlib", "PIL", "dlai_tools",
    "tensorflow", "keras", "termcolor", "imageio", "pandas", "IPython",
    "emoji", "babel", "faker", "mido", "music21", "pydub", "torch",
    "datasets", "transformers", "seqeval", "tqdm",
}


def course_imports(course):
    # Some original lesson paths exceed MAX_PATH on Windows.
    root = Path("\\\\?\\" + str(ROOT)) if os.name == "nt" else ROOT
    folder = next(root.glob(f"Course {course} -*"))
    statements = set()
    for path in folder.rglob("*"):
        if ".ipynb_checkpoints" in path.parts or path.suffix not in {".py", ".ipynb"}:
            continue
        text = path.read_text(encoding="utf-8-sig")
        sources = [text] if path.suffix == ".py" else [
            "".join(cell["source"]) for cell in json.loads(text)["cells"] if cell["cell_type"] == "code"
        ]
        for source in sources:
            # Individual import statements also cover cells with incomplete exercise syntax.
            for line in source.splitlines():
                try:
                    tree = ast.parse(line.strip())
                except SyntaxError:
                    continue
                for node in tree.body:
                    if isinstance(node, ast.ImportFrom) and not node.level:
                        if (node.module or "").split(".")[0] in EXTERNAL:
                            statements.add(ast.unparse(node))
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.split(".")[0] in EXTERNAL:
                                statements.add("import " + alias.name)
            # Include multiline imports in syntactically complete modules/cells.
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and not node.level:
                    if (node.module or "").split(".")[0] in EXTERNAL:
                        statements.add(ast.unparse(node))
    for statement in sorted(statements):
        exec(statement, {})
    print(f"Course {course}: {len(statements)} third-party import statements OK", flush=True)


def check_libraries(course):
    import numpy as np
    import h5py
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    from scipy.special import expit
    from sklearn.datasets import make_moons

    assert sys.version_info[:3] == (3, 10, 20), sys.version
    assert np.__version__ == "1.23.5"
    assert np.isclose(expit(0), 0.5)
    assert make_moons(10, random_state=1)[0].shape == (10, 2)
    for module in ("ipykernel", "ipywidgets", "pip"):
        importlib.import_module(module)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        with h5py.File(path / "test.h5", "w") as f:
            f["values"] = np.arange(3)
        with h5py.File(path / "test.h5") as f:
            np.testing.assert_array_equal(f["values"][:], np.arange(3))
        plt.plot([0, 1], [0, 1])
        plt.savefig(path / "plot.png")
        plt.close()
        with Image.open(path / "plot.png") as picture:
            assert picture.width > 0
    course_imports(course)
    if course in (2, 4, 5):
        import tensorflow as tf
        import tensorboard.default
        assert tf.__version__.startswith("2.10."), tf.__version__
        tf.config.set_visible_devices([], "GPU")
        x = tf.Variable([1.0, 2.0])
        with tf.GradientTape() as tape:
            loss = tf.reduce_sum(x * x)
        np.testing.assert_allclose(tape.gradient(loss, x).numpy(), [2.0, 4.0])
        model = tf.keras.Sequential([tf.keras.layers.Dense(2, input_shape=(3,))])
        # Original notebooks use the pre-Keras-3 optimizer and HDF5/SavedModel APIs.
        model.compile(optimizer=tf.keras.optimizers.Adam(lr=0.01, decay=0.01), loss="mse")
        assert np.isfinite(model.train_on_batch(np.ones((2, 3)), np.zeros((2, 2))))
        with tempfile.TemporaryDirectory() as directory:
            model.save(directory)
            restored = tf.keras.models.load_model(directory)
            np.testing.assert_allclose(model(np.ones((1, 3))), restored(np.ones((1, 3))))
        if course == 4:
            from tensorflow.keras.layers.experimental.preprocessing import RandomFlip
            assert RandomFlip()(tf.zeros((1, 8, 8, 3))).shape == (1, 8, 8, 3)
    if course == 5:
        import emoji
        import torch
        from music21 import note, stream, converter
        from pydub import AudioSegment
        from pydub.generators import Sine
        from datasets import Dataset, load_from_disk
        from transformers import (
            DistilBertConfig, DistilBertForQuestionAnswering,
            TFDistilBertForTokenClassification, Trainer, TrainingArguments,
        )
        assert emoji.emojize(":heart:", use_aliases=True) != ":heart:"
        wav = io.BytesIO()
        Sine(440).to_audio_segment(duration=50).export(wav, format="wav")
        wav.seek(0)
        assert len(AudioSegment.from_wav(wav)) == 50
        with tempfile.TemporaryDirectory() as directory:
            midi_path = str(Path(directory) / "example.mid")
            stream.Stream([note.Note("C4")]).write("midi", fp=midi_path)
            assert len(converter.parse(midi_path).flat.notes) == 1
            data_path = str(Path(directory) / "dataset")
            Dataset.from_dict({"text": ["hello"]}).save_to_disk(data_path)
            assert load_from_disk(data_path)[0]["text"] == "hello"
            config = DistilBertConfig(vocab_size=32, n_layers=1, n_heads=2, dim=16, hidden_dim=32)
            pt_model = DistilBertForQuestionAnswering(config)
            assert pt_model(input_ids=torch.ones((1, 4), dtype=torch.long)).start_logits.shape == (1, 4)
            tf_model = TFDistilBertForTokenClassification(config)
            assert tf_model(tf.ones((1, 4), dtype=tf.int32)).logits.shape[:2] == (1, 4)
            trainer = Trainer(model=pt_model, args=TrainingArguments(output_dir=directory, no_cuda=True, report_to=[]))
            assert trainer.model is pt_model
    print(f"Course {course}: library and computation checks OK", flush=True)


def check_kernel(name):
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager

    spec = KernelSpecManager().get_kernel_spec(name)
    assert Path(spec.argv[0]).resolve() == Path(sys.executable).resolve(), spec.argv
    manager = KernelManager(kernel_name=name)
    client = None
    try:
        manager.start_kernel(cwd=str(ROOT))
        client = manager.blocking_client()
        client.start_channels()
        client.wait_for_ready(timeout=90)
        code = "import sys, numpy as np; print('DLS_KERNEL_OK'); print(sys.executable); assert np.sum([1,2,3]) == 6"
        message_id = client.execute(code)
        output = ""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            message = client.get_iopub_msg(timeout=max(0.1, deadline - time.monotonic()))
            if message.get("parent_header", {}).get("msg_id") != message_id:
                continue
            content = message["content"]
            if message["msg_type"] == "error":
                raise RuntimeError("\n".join(content["traceback"]))
            if message["msg_type"] == "stream":
                output += content["text"]
            if message["msg_type"] == "status" and content["execution_state"] == "idle":
                break
        assert "DLS_KERNEL_OK" in output and sys.executable in output, output
    finally:
        if client:
            client.stop_channels()
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
    print(f"Kernel {name}: launched and executed successfully", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", required=True, type=int, choices=range(1, 6))
    parser.add_argument("--kernel", required=True)
    args = parser.parse_args()
    check_libraries(args.course)
    check_kernel(args.kernel)
