#! /bin/bash
# Qt writes to XDG_RUNTIME_DIR and complains loudly when it is unset, which
# happens under some display managers and in containers.
if [ -z "${XDG_RUNTIME_DIR}" ]; then
    XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/runtime-$(id -u)"
    mkdir -p "${XDG_RUNTIME_DIR}"
    chmod 700 "${XDG_RUNTIME_DIR}"
    export XDG_RUNTIME_DIR
fi

# -I keeps the host out of the bundled interpreter: no PYTHONPATH or PYTHONHOME,
# no ~/.local/lib/python3.x/site-packages and no current directory on sys.path.
# Any of those can shadow or break bundled modules (issue #27).
exec {{ python-executable }} -I -m tsm "$@"
