from pathlib import Path


def test_supabase_dependency_is_declared_for_deployment():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert any(line.strip().startswith("supabase==") for line in requirements)
