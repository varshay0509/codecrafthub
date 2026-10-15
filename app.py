"""CodeCraftHub: a beginner-friendly Flask REST API backed by a JSON file."""

import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request

app = Flask(__name__)

# Store the data file next to app.py, regardless of the working directory.
DATA_FILE = Path(__file__).resolve().parent / "courses.json"
VALID_STATUSES = {"Not Started", "In Progress", "Completed"}
REQUIRED_FIELDS = ("name", "description", "target_date", "status")

# This lock protects read-modify-write operations within one Python process.
# A JSON file is intended for learning, not concurrent production traffic.
file_lock = Lock()


class StorageError(Exception):
    """Raised when the course file cannot be read or saved."""


def save_courses(courses):
    """Save courses as readable JSON, replacing the file atomically."""
    temporary_path = None
    try:
        # Write to a temporary file first so a failed write does not
        # leave courses.json half-written.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=DATA_FILE.parent,
            prefix=".courses-", suffix=".tmp", delete=False
        ) as temp_file:
            temporary_path = Path(temp_file.name)
            json.dump(courses, temp_file, indent=4, ensure_ascii=False)
            temp_file.write("\n")
        os.replace(temporary_path, DATA_FILE)
    except (OSError, TypeError, ValueError) as exc:
        raise StorageError("Unable to save course data") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_courses():
    """Read the list of courses, creating the file if it is missing."""
    try:
        # Exclusive creation prevents overwriting a file created by
        # another process between checking and opening it.
        try:
            with DATA_FILE.open("x", encoding="utf-8") as file:
                json.dump([], file)
        except FileExistsError:
            pass

        with DATA_FILE.open("r", encoding="utf-8") as file:
            courses = json.load(file)

        if not isinstance(courses, list):
            raise StorageError("Course data file must contain a JSON list")
        return courses
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StorageError("Unable to read course data") from exc


def validate_course(payload):
    """Return an error message for invalid input, or None if valid."""
    if not isinstance(payload, dict):
        return "Request body must be a JSON object"

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        return "Missing required fields: " + ", ".join(missing)

    for field in REQUIRED_FIELDS:
        if not isinstance(payload[field], str) or not payload[field].strip():
            return f"'{field}' must be a non-empty string"

    if payload["status"] not in VALID_STATUSES:
        return "Invalid status. Use: Not Started, In Progress, or Completed"

    target_date = payload["target_date"]
    try:
        parsed = date.fromisoformat(target_date)
        if parsed.isoformat() != target_date:
            raise ValueError("Non-standard date format")
    except ValueError:
        return "Invalid target_date. Use YYYY-MM-DD (e.g. 2026-12-31)"

    return None


def find_course(courses, course_id):
    """Find a course by its integer ID."""
    return next((course for course in courses if course["id"] == course_id), None)


@app.errorhandler(StorageError)
def handle_storage_error(error):
    # Log technical details on the server, not in the API response.
    app.logger.exception("Course storage failure")
    return jsonify({"error": str(error)}), 500


@app.route("/api/courses", methods=["GET"])
def get_courses():
    """GET /api/courses: return all courses."""
    with file_lock:
        courses = load_courses()
    return jsonify(courses), 200


@app.route("/api/courses/<int:course_id>", methods=["GET"])
def get_course(course_id):
    """GET /api/courses/1: return one course."""
    with file_lock:
        courses = load_courses()
    course = find_course(courses, course_id)
    if course is None:
        return jsonify({"error": "Course not found"}), 404
    return jsonify(course), 200


@app.route("/api/courses", methods=["POST"])
def create_course():
    """POST /api/courses: validate, create, and save a new course."""
    payload = request.get_json(silent=True)
    error = validate_course(payload)
    if error:
        return jsonify({"error": error}), 400

    with file_lock:
        courses = load_courses()
        # IDs start at 1. Deleting a course will not renumber others.
        next_id = max((course["id"] for course in courses), default=0) + 1
        course = {
            "id": next_id,
            "name": payload["name"].strip(),
            "description": payload["description"].strip(),
            "target_date": payload["target_date"],
            "status": payload["status"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        courses.append(course)
        save_courses(courses)

    return jsonify(course), 201


@app.route("/api/courses/<int:course_id>", methods=["PUT"])
def update_course(course_id):
    """PUT /api/courses/1: replace editable fields of a course."""
    payload = request.get_json(silent=True)
    error = validate_course(payload)
    if error:
        return jsonify({"error": error}), 400

    with file_lock:
        courses = load_courses()
        course = find_course(courses, course_id)
        if course is None:
            return jsonify({"error": "Course not found"}), 404

        # The ID and original creation timestamp never change.
        course.update({
            "name": payload["name"].strip(),
            "description": payload["description"].strip(),
            "target_date": payload["target_date"],
            "status": payload["status"],
        })
        save_courses(courses)

    return jsonify(course), 200


@app.route("/api/courses/<int:course_id>", methods=["DELETE"])
def delete_course(course_id):
    """DELETE /api/courses/1: remove a course by ID."""
    with file_lock:
        courses = load_courses()
        course = find_course(courses, course_id)
        if course is None:
            return jsonify({"error": "Course not found"}), 404
        courses.remove(course)
        save_courses(courses)

    return jsonify({"message": "Course deleted successfully"}), 200


if __name__ == "__main__":
    # Create courses.json at startup (also created on the first API call).
    with file_lock:
        load_courses()
    # The debug server is for local development only.
    app.run(debug=True)
