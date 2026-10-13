# --- diagnostics bootstrap: install crash/exception logging before app code ---
import os as _diag_os
import sys as _diag_sys

_diag_dir = _diag_os.path.dirname(_diag_os.path.abspath(__file__))
if _diag_dir not in _diag_sys.path:
    _diag_sys.path.insert(0, _diag_dir)
import app_diagnostics  # noqa: E402

app_diagnostics.install_diagnostics()
# --- end diagnostics bootstrap ---

import os
import logging
from flask import Flask, jsonify, request
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, StatementParameterListItem

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)

w = WorkspaceClient()

TABLE_NAME = "workspace.default.twitter_user_stats"

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CS5224 Twitter Analytics</title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f4f6fa;
            margin: 0;
            padding: 50px 20px;
            color: #1e293b;
        }

        .container {
            max-width: 650px;
            margin: auto;
            background: white;
            padding: 35px;
            border-radius: 16px;
            box-shadow: 0 6px 24px rgba(0,0,0,0.08);
        }

        h1 { margin-bottom: 8px; }

        .subtitle { color: #64748b; }

        .search-box {
            display: flex;
            gap: 10px;
            margin-top: 25px;
        }

        input {
            flex: 1;
            min-width: 0;
            padding: 12px;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            font-size: 16px;
        }

        button {
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 18px;
            cursor: pointer;
        }

        button:hover { background: #1d4ed8; }

        .examples { margin-top: 15px; }

        .examples button {
            background: #e2e8f0;
            color: #334155;
            margin: 4px 6px 4px 0;
        }

        .results {
            display: none;
            margin-top: 30px;
        }

        .stats {
            display: flex;
            gap: 15px;
            margin-top: 15px;
        }

        .card {
            flex: 1;
            background: #eff6ff;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }

        .number {
            font-size: 32px;
            font-weight: bold;
            color: #1d4ed8;
        }

        .label { margin-top: 8px; color: #475569; }

        #message { margin-top: 20px; }
    </style>
</head>

<body>
    <div class="container">
        <h1>Twitter Analytics Dashboard</h1>
        <p class="subtitle">
            CS5224 Lab 02 | Cloud-Based Data Analysis
        </p>

        <p>
            Search for a Twitter user to view their
            follower and followee statistics.
        </p>

        <form class="search-box" id="searchForm">
            <input
                type="text"
                id="userId"
                placeholder="Enter Twitter User ID"
                required
                pattern="[0-9]+"
            >
            <button type="submit">Search</button>
        </form>

        <div class="examples">
            <p>Example users:</p>
            <button onclick="searchUser('214328887')">
                214328887
            </button>
            <button onclick="searchUser('107830991')">
                107830991
            </button>
        </div>

        <p id="message"></p>

        <div class="results" id="results">
            <h2 id="displayId"></h2>

            <div class="stats">
                <div class="card">
                    <div class="number" id="followers">-</div>
                    <div class="label">Followers</div>
                </div>

                <div class="card">
                    <div class="number" id="followees">-</div>
                    <div class="label">Followees</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        document.getElementById("searchForm")
            .addEventListener("submit", function(event) {
                event.preventDefault();
                searchUser(document.getElementById("userId").value);
            });

        async function searchUser(userId) {
            document.getElementById("userId").value = userId;
            document.getElementById("results").style.display = "none";
            document.getElementById("message").textContent = "Loading...";

            try {
                const response = await fetch(
                    "/api/user/" + encodeURIComponent(userId)
                );

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || "Request failed");
                }

                document.getElementById("displayId").textContent =
                    "User ID: " + data.user_id;

                document.getElementById("followers").textContent =
                    data.followers_count.toLocaleString();

                document.getElementById("followees").textContent =
                    data.followees_count.toLocaleString();

                document.getElementById("results").style.display = "block";
                document.getElementById("message").textContent = "";

            } catch (error) {
                document.getElementById("message").textContent =
                    "Error: " + error.message;
            }
        }
    </script>
</body>
</html>
"""

@app.route("/api/user/<user_id>")
def get_user_stats(user_id):

    if not user_id.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")

    if not warehouse_id:
        return jsonify({"error": "SQL Warehouse ID not configured"}), 500

    query = f"""
        SELECT user_id, followers_count, followees_count
        FROM {TABLE_NAME}
        WHERE user_id = :user_id
        LIMIT 1
    """

    try:
        response = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=query,
            parameters=[
                StatementParameterListItem(
                    name="user_id",
                    value=user_id,
                    type="STRING"
                )
            ],
            wait_timeout="30s"
        )


        if response.status.state != StatementState.SUCCEEDED:
            return jsonify({"error": "Query did not complete successfully"}), 500

        rows = response.result.data_array or []

        if not rows:
            return jsonify({"error": "User not found"}), 404

        row = rows[0]

        return jsonify({
            "user_id": row[0],
            "followers_count": int(row[1]),
            "followees_count": int(row[2])
        })

    except Exception:
        app.logger.exception("SQL query failed")
        return jsonify({"error": "Failed to query user statistics"}), 500


@app.route("/api/admin/run-analysis", methods=["POST"])
def run_twitter_analysis():
    import hmac

    expected_token = os.environ.get("JOB_TRIGGER_TOKEN")
    provided_token = request.headers.get("X-Job-Token", "")

    if not expected_token or not hmac.compare_digest(
        provided_token, expected_token
    ):
        return jsonify({"error": "Unauthorized"}), 401

    job_id = os.environ.get("TWITTER_ANALYSIS_JOB_ID")

    if not job_id:
        return jsonify({"error": "Job ID not configured"}), 500

    try:
        response = w.jobs.run_now(job_id=int(job_id))

        return jsonify({
            "message": "Spark analysis job submitted",
            "job_id": job_id,
            "run_id": response.run_id,
            "status": "SUBMITTED"
        }), 202

    except Exception:
        app.logger.exception("Failed to start Spark job")
        return jsonify({
            "error": "Failed to start analysis job"
        }), 500


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", "8000"))
    app.run(host=host, port=port)
