import os, sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "development-key-change-before-deployment")
DB = os.path.join(os.path.dirname(__file__), "social.db")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    conn = g.pop("db", None)
    if conn: conn.close()

def init_db():
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, bio TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, user_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS likes(user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, PRIMARY KEY(user_id,post_id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS follows(follower_id INTEGER NOT NULL, followed_id INTEGER NOT NULL, PRIMARY KEY(follower_id,followed_id), CHECK(follower_id != followed_id), FOREIGN KEY(follower_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(followed_id) REFERENCES users(id) ON DELETE CASCADE);
    """)
    conn.commit(); conn.close()

def current_user():
    if "user_id" not in session: return None
    return db().execute("SELECT id,username,bio FROM users WHERE id=?", (session["user_id"],)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first."); return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def index():
    conn = db()
    posts = conn.execute("""SELECT p.*,u.username,
      (SELECT COUNT(*) FROM likes WHERE post_id=p.id) like_count,
      (SELECT COUNT(*) FROM comments WHERE post_id=p.id) comment_count
      FROM posts p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC""").fetchall()
    comments = conn.execute("SELECT c.*,u.username FROM comments c JOIN users u ON u.id=c.user_id ORDER BY c.created_at").fetchall()
    liked_ids = set()
    if "user_id" in session:
        liked_ids = {r["post_id"] for r in conn.execute("SELECT post_id FROM likes WHERE user_id=?", (session["user_id"],))}
    return render_template("index.html", posts=posts, comments=comments, liked_ids=liked_ids, user=current_user())

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        if len(username)<3 or len(password)<6:
            flash("Use a username of at least 3 characters and a password of at least 6."); return render_template("register.html", user=current_user())
        try:
            cur=db().execute("INSERT INTO users(username,password_hash) VALUES(?,?)",(username,generate_password_hash(password)))
            db().commit(); session["user_id"]=cur.lastrowid
            return redirect(url_for("index"))
        except sqlite3.IntegrityError: flash("That username is already taken.")
    return render_template("register.html", user=current_user())

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=db().execute("SELECT * FROM users WHERE username=?",(request.form.get("username","").strip(),)).fetchone()
        if u and check_password_hash(u["password_hash"],request.form.get("password","")):
            session.clear(); session["user_id"]=u["id"]; return redirect(url_for("index"))
        flash("Incorrect username or password.")
    return render_template("login.html", user=current_user())

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("index"))

@app.route("/post", methods=["POST"])
@login_required
def create_post():
    body=request.form.get("body","").strip()
    if body: db().execute("INSERT INTO posts(user_id,body) VALUES(?,?)",(session["user_id"],body[:1000])); db().commit()
    return redirect(url_for("index"))

@app.route("/like/<int:post_id>", methods=["POST"])
@login_required
def like(post_id):
    conn=db()
    exists=conn.execute("SELECT 1 FROM likes WHERE user_id=? AND post_id=?",(session["user_id"],post_id)).fetchone()
    if exists: conn.execute("DELETE FROM likes WHERE user_id=? AND post_id=?",(session["user_id"],post_id))
    else: conn.execute("INSERT OR IGNORE INTO likes(user_id,post_id) VALUES(?,?)",(session["user_id"],post_id))
    conn.commit(); return redirect(request.referrer or url_for("index"))

@app.route("/comment/<int:post_id>", methods=["POST"])
@login_required
def comment(post_id):
    body=request.form.get("body","").strip()
    if body and db().execute("SELECT id FROM posts WHERE id=?",(post_id,)).fetchone():
        db().execute("INSERT INTO comments(post_id,user_id,body) VALUES(?,?,?)",(post_id,session["user_id"],body[:500])); db().commit()
    return redirect(request.referrer or url_for("index"))

@app.route("/user/<username>")
def profile(username):
    conn=db()
    person=conn.execute("SELECT id,username,bio FROM users WHERE username=?",(username,)).fetchone()
    if not person: flash("User not found."); return redirect(url_for("index"))
    posts=conn.execute("""SELECT p.*,(SELECT COUNT(*) FROM likes WHERE post_id=p.id) like_count,
      (SELECT COUNT(*) FROM comments WHERE post_id=p.id) comment_count FROM posts p WHERE user_id=? ORDER BY created_at DESC""",(person["id"],)).fetchall()
    followers=conn.execute("SELECT COUNT(*) n FROM follows WHERE followed_id=?",(person["id"],)).fetchone()["n"]
    following=conn.execute("SELECT COUNT(*) n FROM follows WHERE follower_id=?",(person["id"],)).fetchone()["n"]
    is_following=False
    if "user_id" in session and session["user_id"] != person["id"]:
        is_following=bool(conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",(session["user_id"],person["id"])).fetchone())
    return render_template("profile.html", profile_user=person, posts=posts, followers=followers, following=following, is_following=is_following, user=current_user())

@app.route("/follow/<int:user_id>", methods=["POST"])
@login_required
def follow(user_id):
    if user_id != session["user_id"] and db().execute("SELECT id FROM users WHERE id=?",(user_id,)).fetchone():
        conn=db(); exists=conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",(session["user_id"],user_id)).fetchone()
        if exists: conn.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?",(session["user_id"],user_id))
        else: conn.execute("INSERT OR IGNORE INTO follows(follower_id,followed_id) VALUES(?,?)",(session["user_id"],user_id))
        conn.commit()
    return redirect(request.referrer or url_for("index"))

@app.route("/bio", methods=["POST"])
@login_required
def bio():
    text=request.form.get("bio","").strip()[:250]
    db().execute("UPDATE users SET bio=? WHERE id=?",(text,session["user_id"])); db().commit()
    user=current_user(); return redirect(url_for("profile", username=user["username"]))

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
