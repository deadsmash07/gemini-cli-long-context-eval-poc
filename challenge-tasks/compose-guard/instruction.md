Build a CLI named compose-guard. Tests run it inside the container.

The executable must be installed at /usr/local/bin/compose-guard.

Input is one or more paths. For directories, scan recursively for docker-compose.yml, docker-compose.yaml, compose.yml, compose.yaml. If a compose file has a sibling .env, treat it as that file's dotenv. Ignore non-compose files. Support v2 and v3 syntax.

Resolve service inheritance via extends (including cross-file via the file key). Resolve the file path relative to the compose file that declares extends. Apply child overrides on top of the parent to form an effective service. If an extends cycle is detected, report exactly one violation for that cycle and continue.

Interpolate environment before policy checks. Precedence (highest to lowest): process environment -> inline service environment -> env_file contents -> the sibling .env. Merge without clobbering higher-precedence values. Missing variables expand to empty string.

Enforce two policies and always print a JSON array to STDOUT with exit code 0. Order the array by source file path, then service name, then field path.

IMAGE_IMMUTABLE: a service's image is compliant only if it uses an OCI digest (@sha256). build-only services are exempt; if both image and build exist, check image.

HEALTHCHECK_AND_LIMITS: any service that exposes ports (ports set or network_mode: host) or declares depends_on must define a healthcheck (has test or cmd) and resource limits (v3: deploy.resources.limits; v2: mem_limit and/or cpus). Reservations alone do not satisfy limits.

Each violation object includes rule, service, path, message and object where object has file and version. Example path: services.api.image.
