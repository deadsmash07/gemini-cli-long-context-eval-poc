#!/bin/bash
cat > /usr/local/bin/cron-guard << 'PY'
#!/usr/bin/env python3
import os, sys, json, glob, re

INPUT="/app/input"
CRONTAB=os.path.join(INPUT,"crontab")
CROND=os.path.join(INPUT,"crontab.d")
OUTDIR="/app/output"
OUT=os.path.join(OUTDIR,"cron-guard.json")

USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

def is_comment_or_blank(s):
    return (not s) or s.lstrip().startswith("#")

def is_env_line(s):
    if "=" not in s or s.strip().startswith(" "):
        return False
    k = s.split("=",1)[0].strip()
    return k and k.replace("_","").isalnum() and k[0].isalpha()

def parse_jobs_from_file(path, source, has_user):
    jobs = []
    env = {}
    with open(path,"r",encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            line = raw.strip()
            if is_comment_or_blank(line):
                continue
            if is_env_line(line):
                k, v = line.split("=",1)
                env[k.strip()] = v.strip()
                continue
            findings = []
            if has_user:
                parts = line.split(maxsplit=6)
                if len(parts) < 6:
                    continue
                sched = " ".join(parts[:5])
                if len(parts) < 7:
                    user = None
                    cmd = " ".join(parts[5:])
                    findings.append({"type":"invalid_user_field","severity":"high","field":"user"})
                else:
                    maybe_user = parts[5]
                    if USER_RE.match(maybe_user):
                        user = maybe_user
                        cmd = parts[6]
                    else:
                        user = None
                        cmd = " ".join(parts[5:])
                        findings.append({"type":"invalid_user_field","severity":"high","field":"user"})
            else:
                parts = line.split(maxsplit=5)
                if len(parts) < 6:
                    continue
                sched = " ".join(parts[:5])
                user = None
                cmd = parts[5]

            if "PATH" not in env:
                findings.append({"type":"missing_path","severity":"medium","field":"env:PATH"})
            if "sudo " in cmd:
                findings.append({"type":"uses_sudo","severity":"high","field":"command"})
            mailto = env.get("MAILTO","")
            if ">" not in cmd and mailto == "":
                findings.append({"type":"no_output_capture","severity":"medium","field":"command"})

            jobs.append({
                "source": source,
                "line_no": i,
                "schedule": sched,
                "user": user,
                "command": cmd,
                "env": dict(env),
                "findings": findings
            })
    return jobs

def main():
    files = []
    if os.path.exists(CRONTAB):
        files.append(("crontab", CRONTAB, False))
    if os.path.isdir(CROND):
        for p in sorted(glob.glob(os.path.join(CROND,"*.conf"))):
            files.append((f"crontab.d/{os.path.basename(p)}", p, True))

    all_jobs = []
    for src, path, has_user in files:
        all_jobs.extend(parse_jobs_from_file(path, src, has_user))

    keymap = {}
    for idx, j in enumerate(all_jobs):
        k = (j["schedule"], j["command"])
        keymap.setdefault(k, []).append(idx)
    dup_count = 0
    for idxs in keymap.values():
        if len(idxs) > 1:
            dup_count += len(idxs)
            for i in idxs:
                all_jobs[i]["findings"].append({
                    "type":"duplicate_job","severity":"medium","field":"schedule+command"
                })

    all_jobs.sort(key=lambda j:(j["source"], j["line_no"]))

    total_findings = sum(len(j["findings"]) for j in all_jobs)
    high_findings = sum(1 for j in all_jobs for f in j["findings"] if f["severity"]=="high")

    summary = {
        "total_jobs": len(all_jobs),
        "total_findings": total_findings,
        "high_findings": high_findings,
        "jobs_without_path": sum(1 for j in all_jobs if "PATH" not in j["env"]),
        "uses_sudo_count": sum(1 for j in all_jobs for f in j["findings"] if f["type"]=="uses_sudo"),
        "no_output_capture_count": sum(1 for j in all_jobs for f in j["findings"] if f["type"]=="no_output_capture"),
        "duplicate_job_count": dup_count
    }

    rep = {"jobs": all_jobs, "summary": summary}
    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f:
        json.dump(rep, f, separators=(",",":"))
    sys.exit(1 if high_findings > 0 else 0)

if __name__ == "__main__":
    main()
PY
chmod +x /usr/local/bin/cron-guard
