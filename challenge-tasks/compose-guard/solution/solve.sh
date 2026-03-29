#!/usr/bin/env bash
set -euo pipefail

cat > /usr/local/bin/compose-guard <<'PY'
#!/usr/bin/env python3
import os, sys, json, yaml, pathlib
from typing import Any, Dict, List, Tuple, Optional, Set

COMPOSE_NAMES = ("docker-compose.yml","docker-compose.yaml","compose.yml","compose.yaml")
# Track reported cycles across the entire run to avoid duplicates
REPORTED_CYCLES: Set[Tuple[str,str,str]] = set()  # (file, a_service, b_service) sorted by service name

def find_compose_files(path: str) -> List[pathlib.Path]:
    p = pathlib.Path(path)
    out = []
    if p.is_file() and p.name in COMPOSE_NAMES:
        out.append(p)
    elif p.is_dir():
        for f in p.rglob("*"):
            if f.name in COMPOSE_NAMES:
                out.append(f)
    return sorted(out, key=lambda x: str(x))

def load_env_file(p: pathlib.Path) -> Dict[str,str]:
    envp = p.with_name(".env")
    vals = {}
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            s=line.strip()
            if not s or s.startswith("#") or "=" not in s: continue
            k,v = s.split("=",1)
            vals[k.strip()] = v.strip()
    return vals

def read_env_file(path: pathlib.Path) -> Dict[str,str]:
    vals={}
    if not path: return vals
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s=line.strip()
            if not s or s.startswith("#") or "=" not in s: continue
            k,v = s.split("=",1)
            vals[k.strip()] = v.strip()
    return vals

def interp(value: Any, env: Dict[str,str]) -> Any:
    if isinstance(value,str):
        out = ""
        i=0
        s=value
        while i < len(s):
            if s[i] == "$" and i+1 < len(s) and s[i+1] == "{":
                j = s.find("}", i+2)
                if j==-1:
                    out += s[i]; i+=1; continue
                key = s[i+2:j]
                out += env.get(key,"")
                i = j+1
            else:
                out += s[i]; i+=1
        return out
    if isinstance(value,list):
        return [interp(x, env) for x in value]
    if isinstance(value,dict):
        return {k:interp(v, env) for k,v in value.items()}
    return value

def merge_env_for_service(base_env: Dict[str,str], inline_env: Any, env_files: List[str], compose_dir: pathlib.Path) -> Dict[str,str]:
    merged = {}
    # precedence: process env > inline > env_file > .env
    for ef in env_files or []:
        ep = (compose_dir / ef).resolve()
        merged.update(read_env_file(ep))
    if isinstance(inline_env, list):
        for kv in inline_env:
            if isinstance(kv,str) and "=" in kv:
                k,v = kv.split("=",1)
                merged[k]=v
    elif isinstance(inline_env, dict):
        for k,v in inline_env.items():
            merged[str(k)] = str(v)
    top=os.environ
    final = dict(base_env)
    for k,v in merged.items():
        final[k]=v
    for k,v in top.items():
        final[k]=v
    return final

def load_yaml(p: pathlib.Path) -> Dict[str,Any]:
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict): return {}
    return data

def _report_cycle_once(violations: List[Dict[str,Any]], compose_file: pathlib.Path, a_service: str, b_service: str):
    a, b = sorted([a_service or "", b_service or ""])
    key = (str(compose_file), a, b)
    if key in REPORTED_CYCLES:
        return
    REPORTED_CYCLES.add(key)
    violations.append({
        "rule":"EXTENDS_CYCLE",
        "service": a_service,
        "path": f"services.{a_service}.extends",
        "message":"cycle detected in extends",
        "object":{"file":str(compose_file), "version":""},
    })

def resolve_extends(service_name: str, service: Dict[str,Any], compose_file: pathlib.Path, seen: Set[Tuple[pathlib.Path,str]]) -> Tuple[Dict[str,Any], List[Dict[str,Any]]]:
    violations=[]
    if "extends" not in service:
        return service, violations
    ext = service.get("extends") or {}
    parent_service = ext.get("service")
    parent_file = ext.get("file")
    parent_path = compose_file
    if parent_file:
        parent_path = (compose_file.parent / parent_file).resolve()
    key = (parent_path, parent_service or "")
    if key in seen:
        _report_cycle_once(violations, compose_file, service_name, parent_service or "")
        return service, violations
    try:
        pdata = load_yaml(parent_path)
        psvcs = (pdata.get("services") or {})
        if parent_service not in psvcs:
            violations.append({
                "rule":"EXTENDS_MISSING",
                "service": service_name,
                "path": f"services.{service_name}.extends",
                "message":f"parent service '{parent_service}' not found",
                "object":{"file":str(compose_file), "version":str(pdata.get("version",""))},
            })
            return service, violations
        parent = psvcs[parent_service] or {}
        eff_parent, v2 = resolve_extends(parent_service, parent, parent_path, seen | {key})
        violations.extend(v2)
        merged = dict(eff_parent)
        for k,v in service.items():
            if k=="extends": continue
            if isinstance(v,dict) and isinstance(merged.get(k),dict):
                mv = dict(merged[k]); mv.update(v); merged[k]=mv
            else:
                merged[k]=v
        return merged, violations
    except Exception as e:
        violations.append({
            "rule":"EXTENDS_ERROR",
            "service": service_name,
            "path": f"services.{service_name}.extends",
            "message":str(e),
            "object":{"file":str(compose_file), "version":""},
        })
        return service, violations

def has_ports_or_host_net(svc: Dict[str,Any]) -> bool:
    if svc.get("network_mode") == "host":
        return True
    prt = svc.get("ports")
    return bool(prt)

def has_healthcheck(svc: Dict[str,Any]) -> bool:
    hc = svc.get("healthcheck")
    if not hc: return False
    return any(k in hc for k in ("test","cmd"))

def has_limits_v3(svc: Dict[str,Any]) -> bool:
    dep = svc.get("deploy") or {}
    res = dep.get("resources") or {}
    lim = res.get("limits") or {}
    return bool(lim)

def has_limits_v2(svc: Dict[str,Any]) -> bool:
    return bool(svc.get("mem_limit") or svc.get("cpus"))

def image_is_digest(img: str) -> bool:
    return img and "@sha256:" in img

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: compose-guard <file-or-dir> [...]", file=sys.stderr)
        return 2
    all_violations: List[Dict[str,Any]] = []
    inputs = argv[1:]
    files: List[pathlib.Path] = []
    for arg in inputs:
        files.extend(find_compose_files(arg))
    for cf in files:
        data = load_yaml(cf)
        version = str(data.get("version",""))
        services = data.get("services") or {}
        dot_env = load_env_file(cf)
        for name in sorted(services.keys()):
            raw = services[name] or {}
            eff, vios = resolve_extends(name, raw, cf, set())
            all_violations.extend(vios)
            inline_env = eff.get("environment")
            env_files = eff.get("env_file") or []
            if isinstance(env_files,str): env_files=[env_files]
            base_env = dict(dot_env)
            env = merge_env_for_service(base_env, inline_env, env_files, cf.parent)
            eff_interp = interp(eff, env)
            img = eff_interp.get("image")
            build = eff_interp.get("build")
            if img and not image_is_digest(str(img)):
                all_violations.append({
                    "rule":"IMAGE_IMMUTABLE",
                    "service": name,
                    "path": f"services.{name}.image",
                    "message":"image must use @sha256 digest",
                    "object":{"file":str(cf), "version":version},
                })
            if has_ports_or_host_net(eff_interp) or bool(eff_interp.get("depends_on")):
                ok_hc = has_healthcheck(eff_interp)
                ok_lim = has_limits_v3(eff_interp) or has_limits_v2(eff_interp)
                if not ok_hc:
                    all_violations.append({
                        "rule":"HEALTHCHECK_AND_LIMITS",
                        "service": name,
                        "path": f"services.{name}.healthcheck",
                        "message":"service exposes ports or dependencies and must define healthcheck",
                        "object":{"file":str(cf), "version":version},
                    })
                if not ok_lim:
                    rep = "services.%s.deploy.resources.limits" % name if version.startswith("3") else f"services.{name}.mem_limit"
                    all_violations.append({
                        "rule":"HEALTHCHECK_AND_LIMITS",
                        "service": name,
                        "path": rep,
                        "message":"service must set resource limits",
                        "object":{"file":str(cf), "version":version},
                    })
    def key(v):
        return (v.get("object",{}).get("file",""), v.get("service",""), v.get("path",""))
    all_violations.sort(key=key)
    print(json.dumps(all_violations, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
chmod +x /usr/local/bin/compose-guard
