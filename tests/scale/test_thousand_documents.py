import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import psutil
import pytest

from docgen.models import content_hash
from docgen.pipeline import resume, validate
from docgen.store import RunStore
from tests.test_process_recovery import stop_owned_tree


def test_thousand_real_artifacts_meet_exact_mix_integrity_and_memory_bound(tmp_path: Path) -> None:
    signal = tmp_path / "scale-checkpoint.json"
    output = tmp_path / "runs"
    script = r"""
import json,socket,sys,time
from pathlib import Path
import docgen.rendering as rendering
from docgen.config import Config
from docgen.pipeline import run
from tests.test_generate_phase import BatchProvider
from tests.test_planning import configuration
output=Path(sys.argv[1]); signal=Path(sys.argv[2])
data=configuration(1000)
data["generation"]["limits"]={"concurrency":2}
data["rendering"]["weights"]={
    "pdf":.25,"docx":.25,"xlsx":.15,"pptx":.15,"html":.1,"md":.1,
}
def forbidden(*args,**kwargs):
    raise AssertionError("Network access is forbidden in the scale worker.")
socket.socket.connect=forbidden
socket.socket.connect_ex=forbidden
socket.create_connection=forbidden
source=BatchProvider()
renderer=rendering.render_document
written=0
def checkpoint_render(content,assignment,directory):
    global written
    artifact=renderer(content,assignment,directory)
    written+=1
    if written==37:
        temporary=signal.with_suffix(".pending")
        temporary.write_text(json.dumps({
            "directory":str(Path(directory).parent),
            "requests":len(source.calls),"written_artifacts":written,
        }),encoding="utf-8")
        temporary.replace(signal)
        time.sleep(300)
    return artifact
rendering.render_document=checkpoint_render
result=run(Config.model_validate(data),output,provider=source)
raise AssertionError(f"Worker finished without the injected crash: {result}")
"""
    process = psutil.Process()
    stop = threading.Event()
    peak = [process.memory_info().rss]
    sample_errors: list[psutil.Error] = []

    def sample() -> None:
        try:
            while not stop.wait(0.05):
                usage = process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        usage += child.memory_info().rss
                    except psutil.NoSuchProcess:
                        continue
                peak[0] = max(peak[0], usage)
        except psutil.Error as error:
            sample_errors.append(error)

    sampler = threading.Thread(target=sample, daemon=True)
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None
    sampler.start()
    started = time.monotonic()
    worker = subprocess.Popen(
        [sys.executable, "-c", script, str(output), str(signal)],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 3600
        while not signal.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not signal.exists():
            if worker.poll() is None:
                stopped = stop_owned_tree(powershell, worker.pid)
                assert stopped.returncode == 0, stopped.stderr
            stdout, stderr = worker.communicate(timeout=30)
            pytest.fail(f"Scale worker did not reach its crash checkpoint: {stdout}\n{stderr}")
        checkpoint = json.loads(signal.read_text(encoding="utf-8"))
        directory = Path(checkpoint["directory"])
        assert directory.parent == output
        stopped = stop_owned_tree(powershell, worker.pid)
        assert stopped.returncode == 0, stopped.stderr
        worker.communicate(timeout=30)
        with RunStore.open(directory) as store:
            before = {item.blueprint.content_id: content_hash(item) for item in store.contents()}
            verified_before = {
                key: state.hash
                for key, state in store.rendered_states().items()
                if state.status == "verified"
            }
        assert len(before) == checkpoint["requests"] == 1000
        assert len(verified_before) == checkpoint["written_artifacts"] - 1
        staged_before = {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for file in (directory / "artifacts.pending").iterdir()
        }
        allocation_before = (directory / "allocation.json").read_bytes()
        result = resume(directory)
        assert result.status == "complete", result
        assert result.verified_document_count == result.accepted_count == 1000
        assert result.corpus_path is not None
        assert Counter(file.suffix for file in result.corpus_path.iterdir()) == {
            ".pdf": 250,
            ".docx": 250,
            ".xlsx": 150,
            ".pptx": 150,
            ".html": 100,
            ".md": 100,
        }
        with RunStore.open(directory) as store:
            contents = store.contents()
            states = store.rendered_states()
            assert len({content.normalized_fingerprint for content in contents}) == 1000
            assert len(states) == 1000
            assert {item.blueprint.content_id: content_hash(item) for item in contents} == before
            assert len(store.attempts()) == 1000
            assert all(states[key].hash == expected for key, expected in verified_before.items())
        assert (directory / "allocation.json").read_bytes() == allocation_before
        assert all(
            hashlib.sha256((result.corpus_path / name).read_bytes()).hexdigest() == expected
            for name, expected in staged_before.items()
        )
        assert validate(directory).status == "valid"
        assert resume(directory).status == "complete"
        assert not sample_errors, sample_errors
        assert peak[0] < 1024**3, f"Peak process-tree RSS exceeded 1 GiB: {peak[0]}"
        renamed = directory.with_name(directory.name + "-checked")
        directory.rename(renamed)
        renamed.rename(directory)
        evidence = {
            "count": 1000,
            "peak_process_tree_rss_bytes": peak[0],
            "elapsed_seconds": time.monotonic() - started,
            "document_bytes": sum(file.stat().st_size for file in result.corpus_path.iterdir()),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "requests": 1000,
            "crash_checkpoint_artifact_count": len(staged_before),
            "retained_verified_artifact_count": len(verified_before),
            "dependency_versions": {
                name: version(name)
                for name in (
                    "python-docx",
                    "python-pptx",
                    "openpyxl",
                    "reportlab",
                    "pypdf",
                    "pdfplumber",
                    "networkx",
                )
            },
            "run_id": result.run_id,
        }
        report_path = Path(
            os.environ.get("DOCGEN_SCALE_REPORT", str(tmp_path / "scale-evidence.json"))
        )
        report_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence))
    finally:
        if worker.poll() is None:
            stop_owned_tree(powershell, worker.pid)
            worker.communicate(timeout=30)
        stop.set()
        sampler.join(timeout=10)
