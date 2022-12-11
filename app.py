from flask import Flask, render_template, redirect, request, session, flash
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from nsetools import Nse
from datetime import datetime
from sqlalchemy import func
from functools import wraps

app = Flask(__name__)


app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/stockearn'

db = SQLAlchemy(app)
nse = Nse()

class Users(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    hash = db.Column(db.String(120), nullable=False)
    cash = db.Column(db.Integer, default = 1000000)

class Transactions(db.Model):
    user_id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    quote = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    date = db.Column(db.String(20), nullable=True)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
@login_required
def index():
    stocks = db.session.query(Transactions.symbol,func.sum(Transactions.quantity).label('quantity')).filter_by(user_id=session["user_id"]).group_by(Transactions.symbol).all()
    shares = []
    value = 0
    previous = 0
    for stock in stocks:

        if int(stock.quantity) == 0:
            continue

        quote = nse.get_quote(stock.symbol)
        name = quote.get("companyName")
        price = quote.get("lastPrice")
        total = price*int(stock.quantity)
        shares.append({
            'Symbol':stock.symbol,
            'Name':name,
            'Shares':stock.quantity,
            'Price':price,
            'Total':"{:.1f}".format(total)
        })
        value += total
        previous += float(quote.get("previousClose"))*int(stock.quantity)


    cash = Users.query.filter_by(id=session["user_id"]).first()
    balance = int(cash.cash)
    grand_total = value + balance
    previous += cash.cash

    change = grand_total - previous

    pchange = (change/previous)*100
    if pchange >= 0:
        color = "color:#009688!important"
    else:
        color = "color:#FF5252!important"

    pchange = "{:.2f}".format(pchange)


    overall_change = {'change':grand_total - 1000000}

    grand_total = "{:.2f}".format(grand_total)
    overall_change['percentage'] = "{:.2f}".format((overall_change['change']/1000000)*100)
    change = "{:.2f}".format(change)

    if overall_change['change'] >= 0:
        overall_change['color'] = "color:#009688!important"
    else:
        overall_change['color'] = "color:#FF5252!important"
    overall_change['change'] = "{:.2f}".format(overall_change['change'])

    return render_template("index.html",shares=shares,balance = balance,grand_total=grand_total,overall_change=overall_change,change=change,pchange=pchange,color=color)

@app.route("/quote",methods = ["GET","POST"])
@login_required
def quote():
    if request.method == "POST":
        if not request.form.get("symbol"):
            flash("Must provide a symbol","danger")
            return redirect("/quote")

        quote = nse.get_quote(request.form.get("symbol"))
        if not quote:
            flash("Must provide a valid symbol","danger")
            return redirect("/quote")


        return render_template("quoted.html",quote=quote)

    else:
        return render_template("quote.html")

@app.route("/buy",methods = ["GET","POST"])
@login_required
def buy():
    if request.method == "POST":

        symbol = request.form.get("symbol")
        qty = request.form.get("quantity")

        if not symbol:
            flash("Must provide a symbol","danger")
            return redirect("/buy")
        elif not qty:
            flash("Must provide number of shares","danger")
            return redirect("/buy")
        elif int(qty) < 1:
            flash("Must provide a valid number of shares","danger")
            return redirect("/buy")

        quote = nse.get_quote(symbol)
        qty = int(qty)
        if not quote:
            flash("Must provide a valid symbol","danger")
            return redirect("/buy")

        price = quote.get("lastPrice")
        user = Users.query.filter_by(id = session["user_id"]).first()
        cash = user.cash
        total = qty*price
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if cash >= total:
            user.cash = cash-total
            transaction = Transactions(user_id=session["user_id"],symbol=quote.get("symbol"),quantity=qty,quote=price,total=total,date=date)
            db.session.add(transaction)
            db.session.commit()
            flash("Successfully bought!","success")
            return redirect("/")

        else:
            flash("Not enough cash","danger")
            return redirect("/buy")


    else:
        return render_template("buy.html")

@app.route("/sell",methods = ["GET","POST"])
@login_required
def sell():
    stocks = db.session.query(Transactions.symbol,func.sum(Transactions.quantity).label('quantity')).filter_by(user_id=session["user_id"]).group_by(Transactions.symbol).all()
    if request.method == "POST":
        symbol = request.form.get("symbol")
        qty = request.form.get("quantity")
        stock = db.session.query(func.sum(Transactions.quantity).label('quantity')).filter_by(user_id=session["user_id"],symbol=symbol).group_by(Transactions.symbol).first()
        shares = int(stock.quantity)
        if not symbol:
            flash("Must provide a symbol","danger")
            return redirect("/sell")
        elif not qty:
            flash("Must provide number of shares","danger")
            return redirect("/sell")
        elif int(qty) < 1:
            flash("Must provide a valid number of shares","danger")
            return redirect("/sell")
        elif shares < int(qty):
            flash("Not enough number of shares in your portfolio","danger")
            return redirect("/sell")

        qty = int(qty)
        user = Users.query.filter_by(id=session["user_id"]).first()
        price = nse.get_quote(symbol)["lastPrice"]
        cash = user.cash
        total = price*qty
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user.cash = cash+total
        transaction = Transactions(user_id=session["user_id"],symbol=symbol,quantity=-qty,quote=price,total=total,date=date)
        db.session.add(transaction)
        db.session.commit()

        flash("Successfully sold!","success")
        return redirect("/")

    else:
        shares = []
        for stock in stocks:
            if int(stock.quantity) != 0:
                shares.append(stock.symbol)

        return render_template("sell.html",shares=shares)


@app.route("/history")
@login_required
def history():
    transactions = db.session.query(Transactions.symbol,Transactions.quantity,Transactions.quote,Transactions.date).filter_by(user_id=session["user_id"]).order_by(Transactions.date.desc()).all()
    return render_template("history.html",transactions=transactions)

@app.route("/login",methods = ["GET","POST"])
def login():
    if request.method == "POST":
        if not request.form.get("username"):
            flash("Enter username","danger")
            return redirect("/login")
        elif not request.form.get("password"):
            flash("Enter password","danger")
            return redirect("/login")

        user = Users.query.filter_by(username=request.form.get("username")).first()

        if user == None or not check_password_hash(user.hash,request.form.get("password")):
            flash("Incorrect username/password","danger")
            return redirect("/login")

        session["user_id"] = Users.query.filter_by(username=request.form.get("username")).first().id
        flash("Successfully logged in","success")
        return redirect("/")

    else:
        return render_template("login.html")


@app.route("/register",methods = ["GET","POST"])
def register():
    if request.method == "POST":
        if not request.form.get("username"):
            flash("Enter username","danger")
            return redirect("/register")
        elif not request.form.get("password"):
            flash("Enter password","danger")
            return redirect("/register")
        elif not request.form.get("confirmation"):
            flash("Enter password confirmation","danger")
            return redirect("/register")
        elif request.form.get("password") != request.form.get("confirmation"):
            flash("Password don't match","danger")
            return redirect("/register")

        if Users.query.filter_by(username=request.form.get("username")).first() == None:
            pwdhash = generate_password_hash(request.form.get("password"))
            user = Users(username=request.form.get("username"),hash=pwdhash)
            db.session.add(user)
            db.session.commit()
            flash("Registered successfully!","success")
            session["user_id"] = Users.query.filter_by(username=request.form.get("username")).first().id
            return redirect("/")

        else:
            flash("Username already taken!","danger")
            return redirect("/register")
    else:
        return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    session["user_id"] = None
    flash("Logged out","success")
    return redirect("/")


if __name__ == "__main__":
    app.run(debug = True)
