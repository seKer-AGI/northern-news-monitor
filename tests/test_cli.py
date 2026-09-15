import io
import json

import pytest

from app.cli import EXIT_OK, EXIT_PARTIAL, Context, build_parser, main
from app.providers.mock import MockFacebookProvider


@pytest.fixture
def ctx(settings, session_factory, clock):
    return Context(
        settings=settings,
        _session_factory=session_factory,
        provider_factory=lambda _s: MockFacebookProvider(clock=clock),
        out=io.StringIO(),
    )


def _run(ctx, *argv):
    ctx.out.seek(0)
    ctx.out.truncate()
    code = main(list(argv), context=ctx)
    return code, ctx.out.getvalue()


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("collect", "sources", "db", "export", "serve"):
        assert command in out


def test_sources_add_list_and_collect(ctx):
    assert (
        _run(
            ctx, "sources", "add", "--type", "group", "--name", "AI Jobs", "--identifier", "ai-jobs"
        )[0]
        == EXIT_OK
    )
    code, out = _run(ctx, "sources", "list")
    assert code == EXIT_OK and "ai-jobs" in out

    code, out = _run(ctx, "collect")
    assert code == EXIT_OK
    assert json.loads(out)["posts_saved"] > 0

    code, out = _run(ctx, "collect")
    assert json.loads(out)["posts_saved"] == 0


def test_duplicate_source_add_fails(ctx):
    args = ("sources", "add", "--type", "page", "--name", "P", "--identifier", "p")
    assert _run(ctx, *args)[0] == EXIT_OK
    assert _run(ctx, *args)[0] != EXIT_OK


def test_partial_success_exit_code(ctx):
    _run(ctx, "sources", "add", "--type", "page", "--name", "Good", "--identifier", "good")
    _run(
        ctx,
        "sources",
        "add",
        "--type",
        "page",
        "--name",
        "Bad",
        "--identifier",
        "mock-permission-denied",
    )
    assert _run(ctx, "collect")[0] == EXIT_PARTIAL


def test_update_validate_and_runs(ctx):
    _run(ctx, "sources", "add", "--type", "page", "--name", "P", "--identifier", "p")
    assert _run(ctx, "sources", "update", "1", "--deactivate")[0] == EXIT_OK
    assert "No active sources" in _run(ctx, "sources", "list")[1]
    assert _run(ctx, "sources", "validate", "1")[0] == EXIT_OK
    _run(ctx, "collect")
    assert "success" in _run(ctx, "runs", "list")[1]


def test_export_to_file(ctx, tmp_path):
    _run(ctx, "sources", "add", "--type", "group", "--name", "G", "--identifier", "g")
    _run(ctx, "collect")
    target = tmp_path / "posts.json"
    assert _run(ctx, "export", "json", "--output", str(target))[0] == EXIT_OK
    rows = json.loads(target.read_text(encoding="utf-8"))
    assert rows and set(rows[0]) == {"source_name", "source_type", "posted_at", "text"}


def test_provider_health(ctx):
    code, out = _run(ctx, "provider", "health")
    assert code == EXIT_OK and out.startswith("OK")
