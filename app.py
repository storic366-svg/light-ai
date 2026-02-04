from flask import Flask, render_template, request, redirect, session
from textblob import TextBlob
import json, os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret123"

# ---------- BASE PATH ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- JSON HELPERS ----------
def load_json(filename):
    with open(os.path.join(BASE_DIR, filename), "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(os.path.join(BASE_DIR, filename), "w") as f:
        json.dump(data, f, indent=4)

# ---------- LOAD DATA ----------
users = load_json("users.json")
products = load_json("products.json")
reviews = load_json("reviews.json")
purchases = load_json("purchases.json")

# ======================================================
# 🔍 FAKE REVIEW ENGINE (UNCHANGED)
# ======================================================

def user_trust(user):
    score = 50
    if user["account_age_days"] > 180:
        score += 20
    if user["total_reviews"] > 10:
        score += 20
    if user["reported_reviews"] > 0:
        score -= 30
    return max(0, min(score, 100))

def text_score(text):
    blob = TextBlob(text)
    score = 50

    if len(text.split()) < 5:
        score -= 20

    generic_words = ["best", "nice", "good", "awesome"]
    count = sum(text.lower().count(w) for w in generic_words)
    if count > 3:
        score -= 20

    if blob.sentiment.polarity > 0.7:
        score -= 10

    return max(0, min(score, 100))

def rating_mismatch(text, rating):
    polarity = TextBlob(text).sentiment.polarity
    return (rating >= 4 and polarity < 0) or (rating <= 2 and polarity > 0)

def product_rating_mismatch(product_id, rating):
    avg = products[product_id]["average_rating"]
    return abs(rating - avg) >= 2

def timing_check(user_id):
    now = datetime.now()
    recent = 0
    for r in reviews.values():
        if r["user_id"] == user_id:
            t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M")
            if (now - t).total_seconds() < 3600:
                recent += 1
    return recent >= 3

def detect_fake(user, text, rating, user_id, product_id):
    fake_score = 0
    reasons = []

    if user_trust(user) < 40:
        fake_score += 25
        reasons.append("Low user trust")

    if text_score(text) < 40:
        fake_score += 20
        reasons.append("Generic or short review")

    if rating_mismatch(text, rating):
        fake_score += 20
        reasons.append("Rating vs sentiment mismatch")

    if product_rating_mismatch(product_id, rating):
        fake_score += 20
        reasons.append("Rating deviates from product average")

    if timing_check(user_id):
        fake_score += 15
        reasons.append("Too many reviews in short time")

    return ("Fake" if fake_score >= 50 else "Genuine",
            min(fake_score, 100),
            reasons)

# ======================================================
# 🔐 AUTHENTICATION
# ======================================================

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        for uid, user in users.items():
            if user["username"] == request.form["username"] and user["password"] == request.form["password"]:
                session["user_id"] = uid
                session["role"] = user["role"]
                return redirect("/dashboard")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        uid = f"u{len(users)+1:03}"
        users[uid] = {
            "username": request.form["username"],
            "password": request.form["password"],
            "role": "user",
            "account_age_days": 0,
            "total_reviews": 0,
            "reported_reviews": 0
        }
        save_json("users.json", users)
        return redirect("/login")
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ======================================================
# 🧑 USER DASHBOARD (AUTO PURCHASED PRODUCTS)
# ======================================================

@app.route("/dashboard")
def dashboard():
    uid = session.get("user_id")
    if not uid:
        return redirect("/login")

    # 1. Products the user ALREADY owns
    user_purchases = purchases.get(uid, [])
    bought_products = {pid: products[pid] for pid in user_purchases if pid in products}

    # 2. Pass everything to the template
    return render_template("dashboard.html", 
                           products=bought_products, 
                           all_system_products=products)

#===================================================
@app.route("/buy/<product_id>")
def buy_product(product_id):
    uid = session.get("user_id")
    if not uid:
        return redirect("/login")

    # Load current purchases for this user
    user_list = purchases.get(uid, [])

    # Add product if they don't have it yet
    if product_id not in user_list:
        user_list.append(product_id)
        purchases[uid] = user_list
        save_json("purchases.json", purchases)

    return redirect("/dashboard")
# ======================================================
# ✍️ REVIEW PAGE (ONLY BOUGHT PRODUCTS)
# ======================================================
@app.route("/review/<product_id>", methods=["GET", "POST"])
def review(product_id):
    uid = session.get("user_id")
    role = session.get("role")

    # 1. Permission Check (Block Admins)
    if role == "admin":
        return "Admins cannot post reviews.", 403

    # 2. Purchase Check
    if product_id not in purchases.get(uid, []):
        return "You cannot review this product.", 403

    # 3. Handle Form Submission (POST)
    if request.method == "POST":
        rating = float(request.form["rating"])
        text = request.form["review"]
        user = users[uid]

        status, score, reasons = detect_fake(user, text, rating, uid, product_id)

        rid = f"r{len(reviews)+1:03}"
        reviews[rid] = {
            "user_id": uid,
            "product_id": product_id,
            "product_name": products[product_id]["name"],
            "rating": rating,
            "text": text,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result": status,
            "score": score,
            "reasons": reasons
        }

        users[uid]["total_reviews"] += 1
        save_json("reviews.json", reviews)
        save_json("users.json", users)

        # This return handles the POST request
        return redirect("/dashboard")

    # 4. Handle Page Loading (GET)
    # THIS IS THE PART THAT IS LIKELY MISSING OR MISALIGNED IN YOUR CODE
    if product_id in products:
        return render_template("review.html", product=products[product_id], product_id=product_id)
    
    return "Product not found", 404

# ======================================================
# 👑 ADMIN PANEL
# ======================================================
@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return "Access denied"
    return render_template("admin.html", reviews=reviews, products=products)

@app.route("/delete/<rid>")
def delete_review(rid):
    if session.get("role") != "admin":
        return "Access denied"
    reviews.pop(rid, None)
    save_json("reviews.json", reviews)
    return redirect("/admin")
#======================================================
@app.route("/all-reviews")
def all_reviews():
    # TEST: Change this to show ALL reviews first to see if they appear
    # public_data = {rid: r for rid, r in reviews.items()} 
    
    # PRODUCTION: Only show Genuine
    public_data = {rid: r for rid, r in reviews.items() if r.get("result") == "Genuine"}
    
    return render_template("all_reviews.html", reviews=public_data)
# ======================================================
if __name__ == "__main__":
    app.run(debug=True)