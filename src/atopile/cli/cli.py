import sys

# fast-path for self-check
# makes extension a lot faster
if __name__ in ("__main__", "atopile.cli.cli"):
    if len(sys.argv) == 2 and sys.argv[1] == "self-check":
        from importlib.metadata import version as get_package_version

        print(get_package_version("atopile"))
        sys.exit(0)


import json
import logging
from enum import Enum
from importlib.metadata import version as get_package_version
from pathlib import Path
from typing import Annotated

import typer

from atopile import version
from atopile.cli import (
    build,
    configure,
    create,
    dev,
    inspect_,
    install,
    kicad_ipc,
    lsp,
    mcp,
    package,
    serve,
    view,
)
from atopile.errors import (
    UserBadParameterError,
    UserNoProjectException,
    UserResourceException,
    iter_leaf_exceptions,
    log_discord_banner,
)
from atopile.logging import handler, logger
from faebryk.libs.util import ConfigFlag

SAFE_MODE_OPTION = ConfigFlag(
    "SAFE_MODE", False, "Handle exceptions gracefully (coredump)"
)

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,  # Use custom excepthook instead
    rich_markup_mode="rich",
)


def python_interpreter_path(ctx: typer.Context, value: bool):
    """Print the current python interpreter path."""
    if not value or ctx.resilient_parsing:
        return
    typer.echo(sys.executable)
    raise typer.Exit()


def atopile_src_path(ctx: typer.Context, value: bool):
    """Print the current python interpreter path."""
    if not value or ctx.resilient_parsing:
        return
    typer.echo(Path(__file__).parent.parent)
    raise typer.Exit()


def version_callback(ctx: typer.Context, value: bool):
    """Output a version string meeting the pypa version spec."""
    if not value or ctx.resilient_parsing:
        return
    typer.echo(get_package_version("atopile"))
    raise typer.Exit()


def semver_callback(ctx: typer.Context, value: bool):
    """Output a version string meeting the semver.org spec."""
    if not value or ctx.resilient_parsing:
        return
    version_string = get_package_version("atopile")
    typer.echo(version.parse(version_string))
    raise typer.Exit()


@app.callback()
def cli(
    ctx: typer.Context,
    non_interactive: Annotated[
        bool | None,
        typer.Option(
            "--non-interactive", envvar=["ATO_NON_INTERACTIVE", "NONINTERACTIVE"]
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Wait to attach debugger on start"),
    ] = False,
    verbose: Annotated[
        int,
        typer.Option("--verbose", "-v", count=True, help="Increase verbosity"),
    ] = 0,
    python_path: Annotated[
        bool, typer.Option(hidden=True, callback=python_interpreter_path)
    ] = False,
    atopile_path: Annotated[
        bool, typer.Option(hidden=True, callback=atopile_src_path)
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = None,
    semver: Annotated[
        bool | None,
        typer.Option("--semver", callback=semver_callback, is_eager=True),
    ] = None,
    safe_mode: Annotated[
        bool,
        typer.Option(
            "--safe", help="Handle exceptions gracefully (coredump)", hidden=True
        ),
    ] = SAFE_MODE_OPTION.get(),
):
    if safe_mode:
        import os
        import resource
        import signal
        import subprocess
        import time

        def enable_core_dumps():
            """Enable core dumps in the child process."""
            try:
                resource.setrlimit(
                    resource.RLIMIT_CORE,
                    (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
                )
            except (ValueError, OSError):
                pass  # Best effort - may fail if system limit is lower

        args = [arg for arg in sys.argv if arg != "--safe"]
        env = os.environ.copy()
        env[SAFE_MODE_OPTION.name] = "N"  # Prevent safe wrapper recursion
        env["ATO_SAFE"] = "1"  # Signal to workers to enable faulthandler

        start_time = time.time()
        result = subprocess.Popen(args, env=env, preexec_fn=enable_core_dumps)
        pid = result.pid
        returncode = result.wait()
        if returncode not in (0, 1):
            from faebryk.libs.util import run_gdb

            print(f"Process exited with code {returncode}, PID was {pid}")
            # Negative return code means killed by signal
            if returncode < 0:
                sig = -returncode
                try:
                    sig_name = signal.Signals(sig).name
                except ValueError:
                    sig_name = f"signal {sig}"
                print(f"Killed by {sig_name}")
            run_gdb(created_after=start_time)
        sys.exit(returncode)

    if debug:
        import debugpy  # pylint: disable=import-outside-toplevel

        debug_port = 5678
        debugpy.listen(("localhost", debug_port))
        logger.info("Starting debugpy on port %s", debug_port)
        debugpy.wait_for_client()

    # set the log level
    if verbose == 1:
        handler.hide_traceback_types = ()
        handler.tracebacks_show_locals = True
    elif verbose == 2:
        handler.tracebacks_suppress_map = {}  # Traceback through atopile infra
    elif verbose >= 3:
        logger.root.setLevel(logging.DEBUG)
        handler.setLevel(logging.DEBUG)
        handler.traceback_level = logging.WARNING

    # FIXME: this won't work properly when configs
    # are reloaded from a pointed-to file (eg in `ato build path/to/file`)
    # from outside a project directory
    if non_interactive is not None:
        from atopile.config import config

        config.interactive = not non_interactive

    # TODO use file to rate-limit check_for_update
    # if ctx.invoked_subcommand:
    #    check_for_update()

    configure.setup()


app.command()(build.build)
app.add_typer(create.create_app, name="create")
app.command(deprecated=True, hidden=True)(install.install)
app.command()(inspect_.inspect)
app.command()(view.view)
app.add_typer(package.package_app, name="package", hidden=True)
app.add_typer(install.dependencies_app, name="dependencies", help="Manage dependencies")
app.command(rich_help_panel="Shortcuts")(install.sync)
app.command(rich_help_panel="Shortcuts")(install.add)
app.command(rich_help_panel="Shortcuts")(install.remove)
app.add_typer(lsp.lsp_app, name="lsp", hidden=True)
app.add_typer(mcp.mcp_app, name="mcp", hidden=True)
app.add_typer(kicad_ipc.kicad_ipc_app, name="kicad-ipc", hidden=True)
app.add_typer(dev.dev_app, name="dev", hidden=True)
app.add_typer(serve.serve_app, name="serve")


@app.command(hidden=True)
def export_config_schema(pretty: bool = False):
    from atopile.config import ProjectConfig

    config_schema = ProjectConfig.model_json_schema()

    if pretty:
        print(json.dumps(config_schema, indent=4))
    else:
        print(json.dumps(config_schema))


class ConfigFormat(str, Enum):
    python = "python"
    json = "json"


@app.command(hidden=True)
def dump_config(format: ConfigFormat = ConfigFormat.python):
    from atopile.config import config
    from atopile.logging_utils import console

    console.print(config.project.model_dump(mode=format))


def _check_import_paths(linker, scope, *, base_file: Path) -> None:
    """
    Eagerly resolve every path import in `scope` (recursing into blocks).

    The compiler only resolves `from "x.ato" import Y` when `Y` is first used,
    so an import of a missing file would otherwise pass unnoticed.
    """
    from atopile.compiler import DslImportError, DslRichException
    from atopile.compiler import ast_types as AST
    from atopile.compiler.build import ImportPathNotFoundError
    from atopile.errors import accumulate

    with accumulate() as accumulator:
        for stmt in scope.stmts.get().as_list():
            if stmt.isinstance(AST.BlockDefinition):
                _check_import_paths(
                    linker,
                    stmt.cast(t=AST.BlockDefinition).scope.get(),
                    base_file=base_file,
                )
                continue
            if not stmt.isinstance(AST.ImportStmt):
                continue
            import_path = stmt.cast(t=AST.ImportStmt).get_path()
            if import_path is None:
                continue  # stdlib import, already checked by the visitor
            with accumulator.collect():
                try:
                    linker._resolver.resolve(raw_path=import_path, base_file=base_file)
                except ImportPathNotFoundError as e:
                    raise DslRichException(
                        message=str(e),
                        original=DslImportError(str(e)),
                        source_node=stmt,
                    ) from e


def _validate_ato_file(path: Path) -> None:
    """
    Compile every module in a single `.ato` file.

    Runs the front end (parse, link imports, validate the type graph) and
    instantiates each top-level module exactly like the `instantiate-app` build
    step does. No solver, part picking, PCB access, or network traffic.
    """
    import faebryk.core.faebrykpy as fbrk
    import faebryk.core.graph as graph
    import faebryk.core.node as fabll
    import faebryk.library._F as F
    from atopile.compiler import DslRichException, DslTypeError, format_message
    from atopile.compiler.build import (
        Linker,
        StdlibRegistry,
        build_file,
        build_stage_2,
    )
    from atopile.config import config

    if path.is_dir():
        raise UserResourceException(
            f"`{path}` is a directory; expected a `.ato` file", markdown=False
        )
    if not path.exists():
        raise UserResourceException(f"`{path}` does not exist", markdown=False)
    if path.suffix != ".ato":
        raise UserResourceException(f"`{path}` is not a `.ato` file", markdown=False)

    # Fresh graphs per file so one broken file can't poison the next
    g = graph.GraphView.create()
    tg = fbrk.TypeGraph.create(g=g)
    linker = Linker(config, StdlibRegistry(tg), tg)

    result = build_file(g=g, tg=tg, import_path=path.name, path=path.resolve())
    build_stage_2(g=g, tg=tg, linker=linker, result=result)
    _check_import_paths(linker, result.ast_root.scope.get(), base_file=path.resolve())

    for type_node in result.state.type_roots.values():
        try:
            root = tg.instantiate_node(type_node=type_node, attributes={})
        except fbrk.TypeGraphInstantiationError as e:
            message = format_message(e)
            raise DslRichException(
                message=message,
                original=DslTypeError(message),
                source_node=fabll.Node.bind_instance(e.node) if e.node else None,
            ) from e

        node = fabll.Node.bind_instance(root)
        F.Parameters.NumericParameter.infer_units_in_tree(node)
        F.Parameters.NumericParameter.validate_predicate_units_in_tree(node)


@app.command(help="Check .ato files for syntax errors and internal consistency")
def validate(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(
            help="`.ato` files to check, relative to the current directory",
            show_default=False,
        ),
    ] = None,
    build: Annotated[
        str | None,
        typer.Option(
            "--build",
            "-b",
            help="Also check the entry file of this build target",
            show_default=False,
        ),
    ] = None,
):
    """
    Compile every module in the given files without building.

    Prints `<path>: ok` per file that compiles; logs every error otherwise.
    Exits 1 if any file failed, 0 if all passed.
    """
    from atopile.config import config

    # pick up project config if we're in a project
    # required for package search path inclusion
    try:
        config.apply_options(entry=None, selected_builds=[build] if build else ())
    except UserNoProjectException:
        if build is not None:
            raise

    files = list(paths or [])
    if build is not None:
        files.append(config.project.builds[build].entry_file_path)
    if not files:
        raise UserBadParameterError(
            "Nothing to validate: pass at least one `.ato` file or `--build`",
            markdown=False,
        )

    failed = False
    for path in files:
        try:
            _validate_ato_file(path)
        except Exception as exc:
            failed = True
            for error in iter_leaf_exceptions(exc):
                logger.error(error, exc_info=error)
        else:
            typer.echo(f"{path}: ok")

    if failed:
        raise typer.Exit(1)


def main():
    """
    CLI entry point with exception handling.

    Exception Contract:
        - UserException (and subclasses): Build failures - log error, exit(1)
        - Other exceptions: Unexpected errors - log error, exit(1)
        - KeyboardInterrupt: User cancelled - exit(130)

    When run as a subprocess by the server (via build_queue.py), the exit
    code determines the build status:
        - exit(0): SUCCESS
        - exit(1): FAILED
        - exit(130): CANCELLED (SIGINT)
    """
    from atopile import telemetry

    try:
        app()
    except KeyboardInterrupt:
        logger.info("Interrupted")
        raise SystemExit(130)  # Standard exit code for SIGINT
    except Exception as exc:
        for e in iter_leaf_exceptions(exc):
            logger.error(e, exc_info=e)
        telemetry.capture_exception(exc)
        log_discord_banner()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
