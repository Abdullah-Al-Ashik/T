
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_publisher_workflows_do_not_run_on_untrusted_events():
    for name in ("scheduler.yml", "maintenance.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "pull_request:" not in text
        assert "pull_request_target" not in text
        assert "issues:" not in text
        assert "contents: read" in text
        assert "persist-credentials: false" in text


def test_external_service_secrets_are_only_in_publisher_job():
    for name in ("scheduler.yml", "maintenance.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        commit_section = text.split("  persist-state:", 1)[1]
        for secret in ("AI_API_KEY", "THREADS_ACCESS_TOKEN"):
            assert f"secrets.{secret}" not in commit_section
        assert "contents: write" in commit_section


def test_no_shell_tracing_or_environment_dump_in_project_code():
    paths = (
        list((ROOT / "src").glob("*.py"))
        + list((ROOT / ".github" / "workflows").glob("*.yml"))
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "set -x" not in text
        assert "printenv" not in text
        assert "os.environ.items()" not in text


def test_no_real_credentials_in_committed_templates():
    # Documentation files are optional; scan every listed file that exists.
    paths = [
        ROOT / "config.json",
        ROOT / "README.md",
        ROOT / "docs" / "SECRETS.md",
    ]
    for path in paths:
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8").lower()
        assert "ghp_" not in text
        assert "ya29." not in text
        assert "sk_live_" not in text


def test_ffmpeg_subprocess_does_not_inherit_credentials(monkeypatch, tmp_path):
    from src import video_analyzer

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not-a-real-video-but-enough-for-subprocess-test")
    seen = {}

    class Result:
        returncode = 0

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        Path(cmd[-1]).write_bytes(b"jpeg-frame")
        return Result()

    monkeypatch.setattr(video_analyzer.subprocess, "run", fake_run)
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "DO_NOT_INHERIT")

    frames, _ = video_analyzer.extract_frames(
        video, max_frames=1, sample_window_seconds=1
    )

    assert "THREADS_ACCESS_TOKEN" not in seen["env"]
    assert "AI_API_KEY" not in seen["env"]
    assert seen["stdin"] is video_analyzer.subprocess.DEVNULL


def test_dry_run_workflow_steps_do_not_receive_threads_secrets():
    for name in ("scheduler.yml", "maintenance.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

        dry = text.split(
            "      - name: Run dry run without credentials", 1
        )[1].split("      - name: Run AI-enabled dry run", 1)[0]

        ai_dry = text.split(
            "      - name: Run AI-enabled dry run", 1
        )[1].split("      - name: Run live publisher", 1)[0]

        assert "secrets." not in dry
        assert "secrets.THREADS_ACCESS_TOKEN" not in ai_dry
        assert "secrets.AI_API_KEY" in ai_dry


def test_publisher_runtime_does_not_install_third_party_packages():
    for name in ("scheduler.yml", "maintenance.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        publish = text.split("  persist-state:", 1)[0]

        assert "pip install" not in publish
        assert "sparse-checkout:" in publish


def test_project_has_no_email_notification_workflow_or_smtp_references():
    workflows = ROOT / ".github" / "workflows"

    assert not (workflows / "email-test.yml").exists()

    paths = (
        list((ROOT / "src").glob("*.py"))
        + list(workflows.glob("*.yml"))
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "SMTP_APP_PASSWORD" not in text
        assert "NOTIFY_EMAIL_TO" not in text
