"""Command-line interface.

Examples::

    python -m app collect
    python -m app sources list
    python -m app sources seed-northern
    python -m app sources add --type page --name "Example Page" --identifier examplepage
    python -m app sources add --type rss --name "Dawn" --identifier dawn --url https://www.dawn.com/feeds/pakistan
    python -m app db migrate
    python -m app export csv --output posts.csv --start-date 2026-09-14
    python -m app export news-csv --since-hours 24 --output exports/northern-weather-news.csv
    python -m app serve
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.time import Clock, parse_date_param, utcnow
from app.db.models import CollectionRun, RunStatus, Source, SourceType
from app.db.session import create_engine_from_url, make_session_factory
from app.providers.base import DataProvider, ProviderError, SourceRef
from app.providers.factory import build_provider
from app.services.collection import CollectionService
from app.services.export import NEWS_EXPORT_COLUMNS, csv_chunks, iter_export_rows, iter_news_rows
from app.services.notifications import build_notifier
from app.services.posts import PostFilters

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_PARTIAL = 3

SOURCE_TYPE_CHOICES = [t.value for t in SourceType]


@dataclass
class Context:
    settings: Settings
    _session_factory: sessionmaker[Session] | None = None
    provider_factory: Callable[[Settings], DataProvider] = build_provider
    out: object = field(default_factory=lambda: sys.stdout)
    clock: Clock = utcnow

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = make_session_factory(
                create_engine_from_url(self.settings.database_url)
            )
        return self._session_factory

    def print(self, *args: object) -> None:
        print(*args, file=self.out)


# --- handlers ---------------------------------------------------------------
def cmd_collect(args: argparse.Namespace, ctx: Context) -> int:
    provider = ctx.provider_factory(ctx.settings)
    try:
        service = CollectionService(
            ctx.session_factory,
            provider,
            ctx.settings,
            notifier=build_notifier(ctx.settings),
            clock=ctx.clock,
        )
        result = service.run(args.source_id or None)
    finally:
        provider.close()
    ctx.print(json.dumps(result.to_dict(), default=str, indent=2, ensure_ascii=False))
    return {
        RunStatus.SUCCESS: EXIT_OK,
        RunStatus.PARTIAL_SUCCESS: EXIT_PARTIAL,
    }.get(RunStatus(result.status), EXIT_FAILED)


def cmd_sources_list(args: argparse.Namespace, ctx: Context) -> int:
    with ctx.session_factory() as session:
        stmt = select(Source).order_by(Source.id)
        if not args.all:
            stmt = stmt.where(Source.active.is_(True))
        sources = session.scalars(stmt).all()
    if not sources:
        ctx.print("No sources configured." if args.all else "No active sources (use --all).")
        return EXIT_OK
    ctx.print(
        f"{'ID':>4}  {'TYPE':<11} {'ACTIVE':<6} {'IDENTIFIER':<28} {'LAST COLLECTED':<26} NAME"
    )
    for s in sources:
        last = s.last_collected_at.isoformat(timespec="seconds") if s.last_collected_at else "-"
        ctx.print(
            f"{s.id:>4}  {s.source_type:<11} {'yes' if s.active else 'no':<6} "
            f"{s.source_identifier:<28} {last:<26} {s.source_name}"
        )
    return EXIT_OK


def cmd_sources_add(args: argparse.Namespace, ctx: Context) -> int:
    from app.api.schemas import SourceCreate

    payload = SourceCreate(
        source_type=args.type,
        source_name=args.name,
        source_identifier=args.identifier,
        source_url=args.url,
        active=not args.inactive,
    )
    with ctx.session_factory() as session:
        source = Source(**{**payload.model_dump(), "source_type": payload.source_type.value})
        session.add(source)
        try:
            session.commit()
        except IntegrityError:
            ctx.print("Error: a source with this type and identifier already exists.")
            return EXIT_FAILED
        ctx.print(f"Created source {source.id}: {source.source_type} {source.source_identifier}")
    return EXIT_OK


def cmd_sources_seed_northern(args: argparse.Namespace, ctx: Context) -> int:
    from app.services.seeds import seed_sources

    with ctx.session_factory() as session:
        created, existing = seed_sources(session)
    ctx.print(f"Northern-areas news/weather sources: {created} added, {existing} already present.")
    return EXIT_OK


def cmd_sources_update(args: argparse.Namespace, ctx: Context) -> int:
    with ctx.session_factory() as session:
        source = session.get(Source, args.id)
        if source is None:
            ctx.print(f"Error: source {args.id} not found.")
            return EXIT_FAILED
        if args.name:
            source.source_name = args.name
        if args.url:
            source.source_url = args.url
        if args.active is not None:
            source.active = args.active
        session.commit()
        ctx.print(f"Updated source {source.id}.")
    return EXIT_OK


def cmd_sources_remove(args: argparse.Namespace, ctx: Context) -> int:
    with ctx.session_factory() as session:
        source = session.get(Source, args.id)
        if source is None:
            ctx.print(f"Error: source {args.id} not found.")
            return EXIT_FAILED
        session.delete(source)
        session.commit()
    ctx.print(f"Deleted source {args.id} and its posts.")
    return EXIT_OK


def cmd_sources_validate(args: argparse.Namespace, ctx: Context) -> int:
    with ctx.session_factory() as session:
        source = session.get(Source, args.id)
        if source is None:
            ctx.print(f"Error: source {args.id} not found.")
            return EXIT_FAILED
        ref = SourceRef(
            source.source_type, source.source_identifier, source.source_name, source.source_url
        )
    provider = ctx.provider_factory(ctx.settings)
    try:
        result = provider.validate_source(ref)
    finally:
        provider.close()
    if result.ok:
        ctx.print(f"OK: source {args.id} is readable ({result.resolved_name}).")
        return EXIT_OK
    ctx.print(f"FAILED [{result.error_code}]: {result.message}")
    return EXIT_FAILED


def cmd_runs_list(args: argparse.Namespace, ctx: Context) -> int:
    with ctx.session_factory() as session:
        runs = session.scalars(
            select(CollectionRun).order_by(CollectionRun.id.desc()).limit(args.limit)
        ).all()
    if not runs:
        ctx.print("No collection runs yet.")
        return EXIT_OK
    ctx.print(
        f"{'ID':>4}  {'STATUS':<16} {'STARTED':<26} {'SOURCES':>7} {'SAVED':>6} {'ERRORS':>6}"
    )
    for r in runs:
        ctx.print(
            f"{r.id:>4}  {r.status:<16} {r.started_at.isoformat(timespec='seconds'):<26} "
            f"{r.sources_processed:>7} {r.posts_saved:>6} {r.error_count:>6}"
        )
    return EXIT_OK


def cmd_db_migrate(args: argparse.Namespace, ctx: Context) -> int:
    from app.db import migrate

    migrate.upgrade(ctx.settings.database_url, args.revision)
    ctx.print(f"Database migrated to {args.revision}.")
    return EXIT_OK


def cmd_db_downgrade(args: argparse.Namespace, ctx: Context) -> int:
    from app.db import migrate

    migrate.downgrade(ctx.settings.database_url, args.revision)
    ctx.print(f"Database downgraded to {args.revision}.")
    return EXIT_OK


def cmd_db_current(args: argparse.Namespace, ctx: Context) -> int:
    from app.db import migrate

    migrate.current(ctx.settings.database_url)
    return EXIT_OK


def cmd_export(args: argparse.Namespace, ctx: Context) -> int:
    filters = PostFilters(
        source_id=args.source_id,
        source_type=args.source_type,
        start_date=parse_date_param(args.start_date) if args.start_date else None,
        end_date=parse_date_param(args.end_date, is_end=True) if args.end_date else None,
    )
    escape = ctx.settings.csv_escape_formulas
    with ctx.session_factory() as session:
        if args.format == "news-csv":
            collected_since = (
                ctx.clock() - timedelta(hours=args.since_hours) if args.since_hours else None
            )
            rows = iter_news_rows(
                session, filters, dedupe=not args.no_dedupe, collected_since=collected_since
            )
            content = "".join(
                csv_chunks(rows, escape_formulas=escape, fieldnames=NEWS_EXPORT_COLUMNS)
            )
        elif args.format == "csv":
            content = "".join(
                csv_chunks(iter_export_rows(session, filters), escape_formulas=escape)
            )
        else:
            content = json.dumps(
                list(iter_export_rows(session, filters)), ensure_ascii=False, indent=2
            )
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
        rows_written = max(content.count("\n") - 1, 0) if args.format != "json" else None
        suffix = f" ({rows_written} lines)" if rows_written is not None else ""
        ctx.print(f"Wrote {args.format.upper()} export to {args.output}{suffix}")
    else:
        ctx.print(content)
    return EXIT_OK


def cmd_provider_health(args: argparse.Namespace, ctx: Context) -> int:
    provider = ctx.provider_factory(ctx.settings)
    try:
        health = provider.health_check()
    finally:
        provider.close()
    ctx.print(f"{'OK' if health.ok else 'FAILED'} [{health.provider}]: {health.message}")
    return EXIT_OK if health.ok else EXIT_FAILED


def cmd_serve(args: argparse.Namespace, ctx: Context) -> int:
    import uvicorn

    uvicorn.run(
        "app.main:create_app", factory=True, host=args.host, port=args.port, reload=args.reload
    )
    return EXIT_OK


# --- parser -----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description=(
            "Northern News Monitor — collect post text from authorized Facebook sources and "
            "northern-areas weather/hazard news from public feeds."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(title="commands", metavar="<command>")

    p = sub.add_parser(
        "collect",
        help="Run one collection now",
        description="Collect new posts from active sources. Exit codes: 0 success, "
        "3 partial success, 1 failed, 2 usage/configuration error.",
    )
    p.add_argument(
        "--source-id", type=int, action="append", help="Only collect this source (repeatable)"
    )
    p.set_defaults(handler=cmd_collect)

    # sources
    sources = sub.add_parser("sources", help="Manage monitored sources")
    ssub = sources.add_subparsers(title="source commands", metavar="<action>")
    p = ssub.add_parser("list", help="List sources")
    p.add_argument("--all", action="store_true", help="Include inactive sources")
    p.set_defaults(handler=cmd_sources_list)
    p = ssub.add_parser("add", help="Add a source")
    p.add_argument("--type", required=True, choices=SOURCE_TYPE_CHOICES)
    p.add_argument("--name", required=True)
    p.add_argument(
        "--identifier",
        required=True,
        help="Page/Group ID or username; a slug for rss/google_news; a location slug for weather",
    )
    p.add_argument("--url", help="Feed URL (required for rss and google_news)")
    p.add_argument("--inactive", action="store_true", help="Create the source paused")
    p.set_defaults(handler=cmd_sources_add)
    p = ssub.add_parser(
        "seed-northern",
        help="Add the default northern-areas weather/hazard news and forecast sources",
    )
    p.set_defaults(handler=cmd_sources_seed_northern)
    p = ssub.add_parser("update", help="Update a source")
    p.add_argument("id", type=int)
    p.add_argument("--name")
    p.add_argument("--url")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--activate", dest="active", action="store_const", const=True)
    group.add_argument("--deactivate", dest="active", action="store_const", const=False)
    p.set_defaults(handler=cmd_sources_update, active=None)
    p = ssub.add_parser("remove", help="Delete a source and its posts")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_sources_remove)
    p = ssub.add_parser("validate", help="Check the provider can read a source")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_sources_validate)

    # runs
    runs = sub.add_parser("runs", help="Inspect collection runs")
    rsub = runs.add_subparsers(title="run commands", metavar="<action>")
    p = rsub.add_parser("list", help="List recent runs")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(handler=cmd_runs_list)

    # db
    db = sub.add_parser("db", help="Database migrations")
    dsub = db.add_subparsers(title="db commands", metavar="<action>")
    p = dsub.add_parser("migrate", help="Apply migrations (default: head)")
    p.add_argument("--revision", default="head")
    p.set_defaults(handler=cmd_db_migrate)
    p = dsub.add_parser("downgrade", help="Revert migrations (default: -1)")
    p.add_argument("--revision", default="-1")
    p.set_defaults(handler=cmd_db_downgrade)
    p = dsub.add_parser("current", help="Show current revision")
    p.set_defaults(handler=cmd_db_current)

    # export
    p = sub.add_parser(
        "export",
        help="Export posts (csv/json) or northern-areas news (news-csv)",
        description="news-csv columns: posted_at_pkt, source_name, source_type, locations, "
        "hazards, text, url (newest first, same story from several outlets collapsed).",
    )
    p.add_argument("format", choices=["csv", "json", "news-csv"])
    p.add_argument("--output", "-o", help="File path (default: stdout)")
    p.add_argument("--source-id", type=int)
    p.add_argument("--source-type", choices=SOURCE_TYPE_CHOICES)
    p.add_argument("--start-date", help="Posted on/after: ISO 8601 datetime or YYYY-MM-DD")
    p.add_argument("--end-date", help="Posted on/before: ISO 8601 datetime or YYYY-MM-DD")
    p.add_argument(
        "--since-hours", type=int, help="news-csv: only items collected in the last N hours"
    )
    p.add_argument(
        "--no-dedupe", action="store_true", help="news-csv: keep the same story from every outlet"
    )
    p.set_defaults(handler=cmd_export)

    # provider
    provider = sub.add_parser("provider", help="Data provider utilities")
    psub = provider.add_subparsers(title="provider commands", metavar="<action>")
    p = psub.add_parser("health", help="Check provider credentials/connectivity")
    p.set_defaults(handler=cmd_provider_health)

    # serve
    p = sub.add_parser("serve", help="Start the REST API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(handler=cmd_serve)

    for name, sp in (("sources", sources), ("runs", runs), ("db", db), ("provider", provider)):
        sp.set_defaults(handler=lambda a, c, _sp=sp: (_sp.print_help(), EXIT_USAGE)[1], _group=name)
    return parser


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return EXIT_USAGE

    if context is None:
        try:
            settings = get_settings()
        except Exception as exc:  # pydantic validation of env vars
            print(f"Configuration error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        configure_logging(settings.log_level, settings.log_format, settings.secret_values())
        context = Context(settings=settings)

    try:
        return args.handler(args, context)
    except AppError as exc:
        print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_USAGE
    except ProviderError as exc:
        print(f"Provider error [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_FAILED
    except OperationalError as exc:
        print(
            f"Database connection failed: {exc.orig or exc}\n"
            "Check that PostgreSQL is running and DATABASE_URL is correct.",
            file=sys.stderr,
        )
        return EXIT_FAILED
    except ValueError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return EXIT_USAGE
