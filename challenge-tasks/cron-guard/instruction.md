Ship a small CLI named cron-guard and install it at /usr/local/bin/cron-guard.

Read /app/input/crontab and any files ending with .conf in /app/input/crontab.d. Lines beginning with # are comments. In the main crontab each job has five schedule fields followed by the command. In cron.d each job has the five fields, then a user, then the command. Lines of the form KEY=VALUE set environment variables for the jobs that follow within the same file.

Write one JSON report to /app/output/cron-guard.json and always write it. For each job include source, line_no, schedule, user, command, env, and findings. Use these finding names and severities exactly. uses_sudo is high when the command contains the text sudo. invalid_user_field is high when a cron.d job line lacks the required user field. missing_path is medium when PATH is not present in the effective environment. no_output_capture is medium when the command has no > redirection and MAILTO is empty. duplicate_job is medium when two or more jobs share the same schedule and command.

Add a summary object with these integer fields exactly. total_jobs, total_findings, high_findings, jobs_without_path, uses_sudo_count, no_output_capture_count, duplicate_job_count.

Keep results deterministic. Read files in a stable order, sort jobs by source then line_no, and sort findings by the same job order then type. Write compact JSON without extra spaces. Exit with code 1 if any high-severity finding exists, otherwise exit 0.
