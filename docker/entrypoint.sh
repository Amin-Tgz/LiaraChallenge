#!/bin/sh
# One image, two roles.
#
# The API and the Worker run identical code against identical dependencies and
# differ only in which process they start. Building two images would mean two
# things to keep in step, and the first time they drifted the symptom would be a
# worker running yesterday's retrieval code against today's index — silent, and
# visible only as degraded answers.
#
# The role is configuration, like everything else in this system (AGENTS.md §7).
set -eu

# `--check` is the container health probe. The worker listens on no port, so
# there is no HTTP response to ask for; what actually matters is whether the
# process this container exists to run is still the process running. Reading
# PID 1's command line answers exactly that and nothing more — a probe that
# passed while the worker had crashed would be worse than no probe at all.
if [ "${1:-}" = "--check" ]; then
    case "${APP_ROLE:-api}" in
        api)
            exec curl -fsS "http://127.0.0.1:${PORT:-8000}/health/live"
            ;;
        worker)
            if tr '\0' ' ' < /proc/1/cmdline | grep -q 'src.worker'; then
                exit 0
            fi
            echo "worker process is not running as PID 1" >&2
            exit 1
            ;;
    esac
fi

case "${APP_ROLE:-api}" in
  api)
    # Schema compatibility is a prerequisite for accepting traffic.  Liara
    # withholds the new release while this process is unhealthy, so a failed
    # migration fails the deployment and leaves the previous healthy release
    # serving.  Only the API owns this step: deploying API before Worker avoids
    # two containers racing the same Alembic revision.
    echo "applying database migrations before API startup"
    alembic upgrade head
    exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    exec python -m src.worker
    ;;
  *)
    # Naming the offending value matters: the failure is a typo in a panel
    # field, and "container exited" alone would send an operator to the logs of
    # the wrong service. See RULES.md §1.
    echo "APP_ROLE=${APP_ROLE} is not a known role; expected 'api' or 'worker'" >&2
    exit 64
    ;;
esac
