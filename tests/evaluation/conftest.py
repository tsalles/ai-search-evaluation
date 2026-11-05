import shutil

import pytest

from docgen.evaluation.corpus import generate_sources
from docgen.evaluation.reference import build_reference
from docgen.evaluation.state import Workspace
from tests.evaluation.fixtures import FamilyProvider, fresh_workspace
from tests.evaluation.test_reference import approve_reference


@pytest.fixture(scope="session")
def fresh_experiment_template(tmp_path_factory):
    with fresh_workspace(tmp_path_factory.mktemp("fresh-evaluation")) as workspace:
        assert generate_sources(workspace, provider=FamilyProvider()).status == "complete"
        build_reference(workspace)
        approve_reference(workspace)
        path = workspace.path
    return path


@pytest.fixture
def staged_workspace(tmp_path, fresh_experiment_template):
    target = tmp_path / fresh_experiment_template.name
    shutil.copytree(fresh_experiment_template, target)
    with Workspace(target) as workspace:
        yield workspace
