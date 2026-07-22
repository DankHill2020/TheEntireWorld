from models.project import all_roots, project_roots, recent_projects, set_active_project


def test_set_active_project_adds_recent_first(tmp_path):
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()
    settings = {"recent_projects": [str(project_a)]}

    active = set_active_project(settings, str(project_b))

    assert active == str(project_b.resolve())
    assert settings["active_project"] == str(project_b.resolve())
    assert recent_projects(settings)[:2] == [str(project_b.resolve()), str(project_a.resolve())]


def test_recent_projects_deduplicates_normalized_paths(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    settings = {"recent_projects": [str(project), str(project.resolve())]}

    assert recent_projects(settings) == [str(project.resolve())]


def test_project_roots_prefers_active_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    settings = {"active_project": str(project), "extra_dirs": [str(tmp_path / "other")]}

    assert project_roots(settings) == [str(project.resolve())]


def test_all_roots_includes_active_project_first(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    settings = {"active_project": str(project), "extra_dirs": []}

    assert all_roots(settings)[0] == str(project)
