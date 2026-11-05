import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from docgen.pipeline import resume
from docgen.store import RunStore
from tests.test_generate_phase import BatchProvider


def stop_owned_tree(powershell: str, pid: int) -> subprocess.CompletedProcess[str]:
    command = f"""
$ErrorActionPreference='Stop'
$owned=[System.Collections.Generic.List[int]]::new()
function Collect-Owned([int]$parentId) {{
    foreach ($child in @(Get-CimInstance Win32_Process -Filter ("ParentProcessId="+$parentId))) {{
        Collect-Owned $child.ProcessId
        $owned.Add($child.ProcessId)
    }}
}}
Collect-Owned {pid}
$owned.Add({pid})
foreach ($ownedId in $owned) {{
    if (Get-Process -Id $ownedId -ErrorAction SilentlyContinue) {{
        Stop-Process -Id $ownedId -Force -ErrorAction Stop
    }}
}}
"""
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("boundary", ["generation", "rendering", "publication"])
def test_known_child_process_termination_releases_locks_and_preserves_checkpoints(
    tmp_path: Path,
    boundary: str,
) -> None:
    signal = tmp_path / "ready.txt"
    script = r"""
import os,sqlite3,sys,time
from pathlib import Path
from docgen.pipeline import generate,render
from docgen.rendering import render_content
from docgen.config import RenderConfig
from docgen.store import RunStore
from tests.test_generate_phase import batch_config,BatchProvider
output=Path(sys.argv[1]); signal=Path(sys.argv[2]); boundary=sys.argv[3]
def pause(path):
    signal.write_text(str(path),encoding='utf-8')
    time.sleep(180)
if boundary=='generation':
    class Source(BatchProvider):
        def generate(self,blueprint,config):
            if blueprint.ordinal==2:
                path=next(output.iterdir())
                pause(path)
            return super().generate(blueprint,config)
    generate(batch_config(2,concurrency=1),output,provider=Source())
else:
    result=generate(batch_config(2,concurrency=1),output,provider=BatchProvider())
    path=output/result.run_id
    if boundary=='rendering':
        def authorize(action,table,column,*args):
            if action==sqlite3.SQLITE_UPDATE and table=='rendered_artifacts' and column=='status':
                pause(path)
            return sqlite3.SQLITE_OK
        with RunStore.open(path) as store:
            store.connection.set_authorizer(authorize)
            render_content(store,RenderConfig(weights={'md':1}))
    else:
        rename=os.rename
        def paused(source,target,*args,**kwargs):
            rename(source,target,*args,**kwargs)
            if Path(target).name=='corpus':
                pause(path)
        os.rename=paused
        render(path,RenderConfig(weights={'md':1}))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "runs"), str(signal), boundary],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None
    try:
        deadline = time.monotonic() + 300
        while not signal.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not signal.exists():
            if process.poll() is None:
                stopped = stop_owned_tree(powershell, process.pid)
                assert stopped.returncode == 0, stopped.stderr
            stdout, stderr = process.communicate(timeout=30)
            pytest.fail(f"Worker did not reach the {boundary} checkpoint: {stdout}\n{stderr}")
        run_directory = Path(signal.read_text(encoding="utf-8"))
        stopped = stop_owned_tree(powershell, process.pid)
        assert stopped.returncode == 0, stopped.stderr
        process.wait(timeout=30)
        with RunStore.open(run_directory) as store:
            before = {
                item.blueprint.content_id: (
                    run_directory / "content" / f"{item.blueprint.content_id}.json"
                ).read_bytes()
                for item in store.contents()
            }
        result = resume(run_directory, provider=BatchProvider())
        assert result.status == ("content_ready" if boundary == "generation" else "complete")
        for content_id, raw in before.items():
            assert (run_directory / "content" / f"{content_id}.json").read_bytes() == raw
    finally:
        if process.poll() is None:
            stop_owned_tree(powershell, process.pid)
            process.wait(timeout=30)
