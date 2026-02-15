import logging
import sys
from pathlib import Path

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS

from job_manager import JobManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Resolve project root (one level up from src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    config_path = Path(__file__).resolve().parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["_base_dir"] = str(PROJECT_ROOT)
    return config


def create_app() -> Flask:
    config = load_config()

    # Ensure directories exist
    base = PROJECT_ROOT
    for dir_key in ["jobs_dir", "logs_dir"]:
        (base / config["paths"][dir_key]).mkdir(parents=True, exist_ok=True)
    (base / config["paths"]["db_path"]).parent.mkdir(parents=True, exist_ok=True)

    # Initialize scheduler
    scheduler = BackgroundScheduler(daemon=True)

    # Initialize job manager
    manager = JobManager(config, scheduler)

    # Register system jobs
    scan_interval = config.get("scheduler", {}).get("scan_interval_seconds", 60)
    scheduler.add_job(
        manager.scan_jobs,
        "interval",
        seconds=scan_interval,
        id="_system_scan",
        replace_existing=True,
    )

    cleanup_hours = config.get("log_retention", {}).get("cleanup_interval_hours", 24)
    scheduler.add_job(
        manager.cleanup_old_logs,
        "interval",
        hours=cleanup_hours,
        id="_system_cleanup",
        replace_existing=True,
    )
    
    # Process pending updates frequently (every 5 seconds)
    scheduler.add_job(
        manager.process_pending_updates,
        "interval",
        seconds=5,
        id="_system_update",
        replace_existing=True,
    )

    # Start scheduler and do initial scan
    scheduler.start()
    manager.scan_jobs()

    # Create Flask app
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )
    CORS(app)  # Enable CORS for all routes
    app.config["manager"] = manager
    app.config["scheduler"] = scheduler

    register_routes(app)
    return app


def register_routes(app: Flask):
    def get_manager() -> JobManager:
        return app.config["manager"]

    @app.route("/")
    def index():
        manager = get_manager()
        jobs = manager.get_jobs()
        failure_count = manager.get_failure_count()
        return render_template("index.html", jobs=jobs, failure_count=failure_count)

    @app.route("/runs")
    def runs():
        manager = get_manager()
        job_id = request.args.get("job_id")
        status = request.args.get("status")
        run_list = manager.get_runs(job_id=job_id, status=status)
        failure_count = manager.get_failure_count()

        # Get job list for filter dropdown
        jobs = manager.get_jobs()
        return render_template(
            "runs.html",
            runs=run_list,
            jobs=jobs,
            failure_count=failure_count,
            filter_job_id=job_id or "",
            filter_status=status or "",
        )

    @app.route("/logs/<path:log_path>")
    def view_log(log_path):
        manager = get_manager()
        content = manager.get_log_content(log_path)
        if content is None:
            return "Log not found", 404
        return content, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/api/reload", methods=["POST"])
    def api_reload():
        manager = get_manager()
        manager.scan_jobs()
        return redirect(url_for("index"))

    @app.route("/api/run/<task>", methods=["POST"])
    def api_run(task):
        manager = get_manager()
        job_id = task
        import threading

        t = threading.Thread(target=manager.execute_job, args=(job_id,))
        t.start()
        return redirect(request.referrer or url_for("index"))

    @app.route("/api/toggle/<task>", methods=["POST"])
    def api_toggle(task):
        manager = get_manager()
        job_id = task
        manager.toggle_job(job_id)
        return redirect(request.referrer or url_for("index"))

    @app.route("/api/jobs")
    def api_list_jobs():
        manager = get_manager()
        jobs = manager.get_jobs()
        return jsonify(jobs)
    
    @app.route("/api/status")
    def api_status():
        manager = get_manager()
        return jsonify(manager.get_system_status())

    @app.route("/api/upload", methods=["POST"])
    def api_upload_job():
        manager = get_manager()
        task = request.form.get("task")
        files = request.files.getlist("files")

        if not task:
            return jsonify({"error": "Task name required"}), 400
        
        if not files:
            return jsonify({"error": "No files uploaded"}), 400

        # Construct job config if provided
        job_config = None
        schedule_type = request.form.get("schedule_type")
        if schedule_type:
            job_config = {
                "name": request.form.get("job_name", task),
                "description": request.form.get("description", ""),
                "entry_point": request.form.get("entry_point", "main.py"),
                "schedule": {"type": schedule_type}
            }
            
            # Parse schedule args
            if schedule_type == "interval":
                for unit in ["seconds", "minutes", "hours", "days"]:
                    val = request.form.get(f"schedule_{unit}")
                    if val and val.isdigit():
                        job_config["schedule"][unit] = int(val)
            elif schedule_type == "cron":
                for unit in ["minute", "hour", "day", "month", "day_of_week"]:
                    val = request.form.get(f"schedule_{unit}")
                    if val:
                        job_config["schedule"][unit] = val

        try:
            job_id = manager.save_job_files(task, files, job_config)
            return jsonify({
                "message": f"Job {job_id} queued for update. Will be applied when system is idle.", 
                "job_id": job_id,
                "status": "queued"
            })
        except Exception as e:
            logger.exception("Upload failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs/<task>/config", methods=["POST"])
    def api_update_config(task):
        manager = get_manager()
        try:
            new_config = request.json
            if not new_config:
                return jsonify({"error": "No config provided"}), 400
            
            success = manager.update_job_config(task, new_config)
            if success:
                return jsonify({"message": "Configuration updated"})
            else:
                return jsonify({"error": "Job not found or update failed"}), 404
        except Exception as e:
            logger.exception("Update config failed")
            return jsonify({"error": str(e)}), 500


app = create_app()

if __name__ == "__main__":
    config = load_config()
    server = config.get("server", {})
    app.run(
        host=server.get("host", "0.0.0.0"),
        port=server.get("port", 5000),
        debug=server.get("debug", False),
    )
