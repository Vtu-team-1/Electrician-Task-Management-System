from flask import Flask, render_template, request, redirect, session, jsonify, flash
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}


# ---------------- DATABASE ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- FILE VALIDATION ----------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------- CREATE TABLES ----------------
def create_tables():
    conn = get_db()

    conn.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS electricians(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, experience TEXT)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY,
        title TEXT,
        location TEXT,
        deadline TEXT,
        electrician_id INTEGER,
        image TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY,
        name TEXT,
        job_id INTEGER,
        electrician_id INTEGER,
        status TEXT,
        report TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY,
        task_id INTEGER,
        comment TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS materials(
        id INTEGER PRIMARY KEY,
        name TEXT,
        quantity INTEGER,
        cost REAL
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY,
        filename TEXT
    )""")

    conn.commit()
    conn.close()


# ---------------- SAMPLE DATA ----------------
def insert_sample():
    conn = get_db()

    user = conn.execute("SELECT * FROM users").fetchone()
    if not user:
        conn.execute("INSERT INTO users VALUES(1,'admin',?,'admin')",
                     (generate_password_hash("admin123"),))
        conn.execute("INSERT INTO users VALUES(2,'elec',?,'electrician')",
                     (generate_password_hash("123"),))

    conn.commit()
    conn.close()


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], p):
            session["user"] = user["username"]
            session["role"] = user["role"]
            session["uid"] = user["id"]

            if user["role"] == "admin":
                return redirect("/")
            else:
                return redirect("/tasks")

        flash("Invalid Login")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------- DASHBOARD ----------------
@app.route("/")
def dashboard():
    if "user" not in session:
        return redirect("/login")
    if session["role"] != "admin":
         return redirect("/tasks")
    
    conn = get_db()

    e = conn.execute("SELECT COUNT(*) FROM electricians").fetchone()[0]
    j = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    t = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='Completed'").fetchone()[0]
    pending = t - completed

    conn.close()

    return render_template("dashboard.html", e=e, j=j, t=t, completed=completed, pending=pending)


# ---------------- API ----------------
@app.route("/api/stats")
def stats():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='Completed'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status!='Completed'").fetchone()[0]
    conn.close()

    return jsonify({"completed": completed, "pending": pending})


# ---------------- ELECTRICIANS ----------------
@app.route("/electricians", methods=["GET", "POST"])
def electricians():
    if "user" not in session:
        return redirect("/login")

    if session["role"] != "admin":
        return "Access Denied"

    conn = get_db()

    if request.method == "POST":
        conn.execute("INSERT INTO electricians(name,phone,experience) VALUES(?,?,?)",
                     (request.form["name"], request.form["phone"], request.form["experience"]))
        conn.commit()

    data = conn.execute("SELECT * FROM electricians").fetchall()
    conn.close()

    return render_template("electricians.html", data=data)


# ---------------- JOBS ----------------
@app.route("/jobs", methods=["GET", "POST"])
def jobs():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()

    if request.method == "POST":
        file = request.files["image"]

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        else:
            filename = None

        conn.execute("INSERT INTO jobs(title,location,deadline,electrician_id,image) VALUES(?,?,?,?,?)",
                     (request.form["title"], request.form["location"],
                      request.form["deadline"], request.form["electrician"], filename))
        conn.commit()

    data = conn.execute("""
        SELECT jobs.*, electricians.name as ename
        FROM jobs LEFT JOIN electricians ON jobs.electrician_id = electricians.id
    """).fetchall()

    electricians = conn.execute("SELECT * FROM electricians").fetchall()
    conn.close()

    return render_template("jobs.html", data=data, electricians=electricians)


# ---------------- TASKS ----------------
@app.route("/tasks", methods=["GET", "POST"])
def tasks():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()

    # ✅ GET filter value
    status = request.args.get("status")

    # ---------------- POST ACTIONS ----------------
    if request.method == "POST":

        # ➕ ADD TASK
        if "name" in request.form:
            conn.execute("""
                INSERT INTO tasks(name,job_id,electrician_id,status)
                VALUES(?,?,?,?)
            """, (
                request.form["name"],
                request.form["job"],
                request.form["electrician"],
                request.form["status"]
            ))
            conn.commit()

        # 📄 UPLOAD REPORT
        if "report" in request.files:
            f = request.files["report"]
            if f and allowed_file(f.filename):
                fname = secure_filename(f.filename)
                f.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))

                conn.execute("""
                    UPDATE tasks SET report=? WHERE id=?
                """, (fname, request.form["task_id"]))
                conn.commit()

        # 💬 ADD COMMENT
        if "comment" in request.form:
            conn.execute("""
                INSERT INTO comments(task_id, comment)
                VALUES(?,?)
            """, (
                request.form["task_id"],
                request.form["comment"]
            ))
            conn.commit()

    # ---------------- FETCH DATA WITH FILTER ----------------
    if session["role"] == "electrician":

        if status:
            data = conn.execute("""
                SELECT tasks.*, jobs.title as jobname
                FROM tasks
                LEFT JOIN jobs ON tasks.job_id = jobs.id
                WHERE tasks.electrician_id = ? AND tasks.status = ?
            """, (session["uid"], status)).fetchall()
        else:
            data = conn.execute("""
                SELECT tasks.*, jobs.title as jobname
                FROM tasks
                LEFT JOIN jobs ON tasks.job_id = jobs.id
                WHERE tasks.electrician_id = ?
            """, (session["uid"],)).fetchall()

    else:

        if status:
            data = conn.execute("""
                SELECT tasks.*, jobs.title as jobname, electricians.name as ename
                FROM tasks
                LEFT JOIN jobs ON tasks.job_id = jobs.id
                LEFT JOIN electricians ON tasks.electrician_id = electricians.id
                WHERE tasks.status = ?
            """, (status,)).fetchall()
        else:
            data = conn.execute("""
                SELECT tasks.*, jobs.title as jobname, electricians.name as ename
                FROM tasks
                LEFT JOIN jobs ON tasks.job_id = jobs.id
                LEFT JOIN electricians ON tasks.electrician_id = electricians.id
            """).fetchall()

    # ---------------- OTHER DATA ----------------
    jobs = conn.execute("SELECT * FROM jobs").fetchall()
    electricians = conn.execute("SELECT * FROM electricians").fetchall()
    comments = conn.execute("SELECT * FROM comments").fetchall()

    conn.close()

    return render_template("tasks.html",
                           data=data,
                           jobs=jobs,
                           electricians=electricians,
                           comments=comments)
# ---------------- MATERIALS ----------------
@app.route("/materials", methods=["GET", "POST"])
def materials():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()

    if request.method == "POST":
        conn.execute("INSERT INTO materials(name,quantity,cost) VALUES(?,?,?)",
                     (request.form["name"], request.form["quantity"], request.form["cost"]))
        conn.commit()

    data = conn.execute("SELECT * FROM materials").fetchall()
    conn.close()

    return render_template("materials.html", data=data)


# ---------------- REPORTS ----------------
@app.route("/reports", methods=["GET", "POST"])
def reports():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()

    if request.method == "POST":
        file = request.files["file"]

        if file and allowed_file(file.filename):
            fname = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))

            conn.execute("INSERT INTO reports(filename) VALUES(?)", (fname,))
            conn.commit()

    total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='Completed'").fetchone()[0]
    electricians = conn.execute("SELECT COUNT(*) FROM electricians").fetchone()[0]

    data = conn.execute("SELECT * FROM reports").fetchall()

    conn.close()

    return render_template("reports.html",
                           reports=data,
                           total_tasks=total_tasks,
                           completed=completed,
                           electricians=electricians)


# ---------------- UPDATE TASK ----------------
@app.route("/update_task", methods=["POST"])
def update_task():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    conn.execute("UPDATE tasks SET status=? WHERE id=?",
                 (request.form["status"], request.form["id"]))
    conn.commit()

    return redirect("/tasks")


# ---------------- RUN ----------------
if __name__ == "__main__":
    if not os.path.exists("static/uploads"):
        os.makedirs("static/uploads")

    create_tables()
    insert_sample()

    app.run(debug=True)