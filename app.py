import json
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("IOU_SECRET_KEY", "dev-secret-key-change-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")


def ensure_data_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)


def load_users():
    ensure_data_file()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_users(users):
    ensure_data_file()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def ensure_user_shape(user):
    """Backfill fields for accounts created before expenses existed."""
    user.setdefault("expenses", [])
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        users = load_users()

        if username not in users:
            flash("Invalid username", "error")
            return render_template("login.html")

        if not check_password_hash(users[username]["password"], password):
            flash("Invalid password", "error")
            return render_template("login.html")

        session["username"] = username
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html")

        users = load_users()

        if username in users:
            flash("Username already exists. Please choose another.", "error")
            return render_template("signup.html")

        users[username] = {"password": generate_password_hash(password), "expenses": []}
        save_users(users)

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/home")
@login_required
def home():
    me = session["username"]
    users = load_users()
    expenses = ensure_user_shape(users.get(me, {}))["expenses"]

    total_owed = sum(e["amount"] for e in expenses if e["direction"] == "owe")
    total_due = sum(e["amount"] for e in expenses if e["direction"] == "receive")

    return render_template(
        "home.html",
        username=me,
        expenses=sorted(expenses, key=lambda e: e["created_at"], reverse=True),
        total_owed=round(total_owed, 2),
        total_due=round(total_due, 2),
        net=round(total_due - total_owed, 2),
    )


@app.route("/add-expense", methods=["POST"])
@login_required
def add_expense():
    me = session["username"]
    direction = request.form.get("direction", "")
    counterparty = request.form.get("counterparty", "").strip()
    amount_raw = request.form.get("amount", "").strip()

    if direction not in ("owe", "receive"):
        flash("Please choose whether you owe or receive money.", "error")
        return redirect(url_for("home"))

    if not counterparty:
        flash("Please enter a username.", "error")
        return redirect(url_for("home"))

    if counterparty == me:
        flash("You can't create an IOU with yourself.", "error")
        return redirect(url_for("home"))

    users = load_users()
    if counterparty not in users:
        flash(f"No IOU user named '{counterparty}' was found.", "error")
        return redirect(url_for("home"))

    try:
        amount = round(float(amount_raw), 2)
    except ValueError:
        flash("Please enter a valid amount.", "error")
        return redirect(url_for("home"))

    if amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for("home"))

    entry_id = uuid.uuid4().hex
    created_at = datetime.now().isoformat(timespec="seconds")
    opposite = "receive" if direction == "owe" else "owe"

    ensure_user_shape(users[me])["expenses"].append({
        "id": entry_id,
        "counterparty": counterparty,
        "direction": direction,
        "amount": amount,
        "created_at": created_at,
    })

    ensure_user_shape(users[counterparty])["expenses"].append({
        "id": entry_id,
        "counterparty": me,
        "direction": opposite,
        "amount": amount,
        "created_at": created_at,
    })

    save_users(users)

    verb = "owe" if direction == "owe" else "will receive from"
    flash(f"Saved! You {verb} {counterparty} \u20b9{amount:.2f}.", "success")
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    ensure_data_file()
    app.run(debug=True)
