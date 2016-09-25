import web
import json, decimal
import pymysql
import auth
import re
import hashlib
from numpy.random import choice

# create Google app & get app ID/secret from:
# https://cloud.google.com/console
auth.parameters['google']['app_id'] = '744074363989-uvvip7u9a5s8p45chbub04eodgb97pns.apps.googleusercontent.com'
auth.parameters['google']['app_secret'] = 'oWgYfKuVSEZ3yPEkkyPnBEsV'

render = web.template.render('templates/')

urls = (
    r"/login", "LoginPage",
    r"/auth/google", "AuthPage",
    r"/auth/google/callback", "AuthCallbackPage",
    '/auth/default', 'DefaultAuth',
    '/auth/register', 'Register',
    '/logout', 'Reset',
    '/availability', 'CheckUsername',
    '/post/([0-9]*)', 'Post',
    '/post/([0-9]*)/fund', 'Fund',
    '/post/([0-9]*)/giveaway', 'Giveaway',
    '/submit', 'SubmitPost',
    '/posts/search', 'PostsQuery',
    '/script/post/close', 'ClosePost',
    '/posts', 'Posts',
    '/', 'Home'
)

web.config.debug = False

app = web.application(urls, globals())

store = web.session.DiskStore('sessions')
session = web.session.Session(app, store,
                              initializer={'uid': None, 'username': 'Guest', 'gID': None, 'profile': None})

conn = pymysql.connect(host='localhost', port=3306, user='root', passwd='', db='crowdbenchmark')
conn_dict = pymysql.connect(host='localhost', port=3306, user='root', passwd='', db='crowdbenchmark', cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()
cur_dict = conn_dict.cursor()

def decimal_default(obj):
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    raise TypeError

def getallposts():
    cur_dict.execute("SELECT * FROM posts;")
    posts = cur_dict.fetchall()
    for post in posts:
        post_id = post.get("post_id")
        cur_dict.execute("SELECT * FROM post_preferences WHERE post_id={};".format(post_id))
        post_preferences = cur_dict.fetchall()
        post['preferences'] = post_preferences
        cur.execute("SELECT username FROM users WHERE uid={};".format(post.get("uid")))
        post['username'] = cur.fetchone()[0]
    return posts

def getposts(field, value):
    cur_dict.execute("DESCRIBE posts;")
    posts_desc = cur_dict.fetchall()
    fields = [column.get("Field") for column in posts_desc]
    if field in fields:
        command = "SELECT * FROM posts WHERE {}={};".format(field, value)
        cur_dict.execute(command)
        return cur_dict.fetchall()
    else:
        return "field does not exist"

def describepost(post_id):
    found = cur_dict.execute("SELECT * FROM posts WHERE post_id={};".format(post_id))
    if found == 0:
        return "post not found"
    post = cur_dict.fetchall()[0]
    cur_dict.execute("SELECT * FROM post_preferences WHERE post_id={};".format(post_id))
    post_preferences = cur_dict.fetchall()
    cur.execute("SELECT username FROM users WHERE uid={};".format(post.get("uid")))
    username = cur.fetchone()[0]
    return {'post': post, 'preferences': post_preferences, 'username': username}

def giveaway(paying_users):
    sum = 0
    for user in paying_users:
        sum = sum + user['amount']
    uid = choice([user['uid'] for user in paying_users], p=[user['amount'] / float(sum) for user in paying_users])
    return uid

def closepost(post_id):
    #1. check if post exists & if user has privileges to close
    found = cur_dict.execute("SELECT * FROM posts WHERE post_id={};".format(post_id))
    if found == 0:
        return "post not found"
    post = cur_dict.fetchall()[0]
    if session.uid != post['uid']:
        return "you do not have permission to close this post"
    if post['status'] == "closed":
        return "post already closed"
    #2. set status of post to closed
    cur.execute("""UPDATE posts SET status="closed" WHERE post_id={};""".format(post_id))
    #3. find winning option
    cur_dict.execute("""SELECT * FROM post_preferences WHERE post_id={};""".format(post_id))
    preferences = cur_dict.fetchall()
    winning_preference = {"pref_id": None, "amount_funded": 0}
    for preference in preferences:
        if preference['amount_funded'] > winning_preference['amount_funded']:
            winning_preference['pref_id'] = preference['pref_id']
            winning_preference['amount_funded'] = preference['amount_funded']
    #4. list users who chose winning option
    paying_users = []
    cur_dict.execute("SELECT * FROM user_preferences WHERE post_id={} AND pref_id={};".format(post_id, winning_preference['pref_id']))
    for preference in cur_dict.fetchall():
        paying_users.append({"uid": preference['uid'], "amount": preference['amount']})
    #5. list users who chose other options
    nonpaying_users = []
    cur_dict.execute("SELECT * FROM user_preferences WHERE post_id={} AND pref_id<>{};".format(post_id, winning_preference['pref_id']))
    for preference in cur_dict.fetchall():
        nonpaying_users.append({"uid": preference['uid'], "amount": preference['amount']})
    #6. If giveaway, select user for giveaway
    if post['giveaway'] == "yes":
        giveaway_uid = giveaway(paying_users)
        cur.execute("UPDATE posts SET giveaway_uid={}".format(giveaway_uid))
    else:
        giveaway_uid = None
    conn.commit()
    #return
    return {"winning preference": winning_preference, "paying users": paying_users, "nonpaying users": nonpaying_users, "winning user": giveaway_uid}  

def getusername(uid):
    found = cur.execute("SELECT username FROM users WHERE uid=\"" + str(uid) + "\";")
    if found == 0:
        return "user not found"
    else:
        return cur.fetchone()[0]
        
def fund(post_id, pref_id, amount):
    found = cur_dict.execute("SELECT * FROM post_preferences WHERE post_id={} AND pref_id={};".format(post_id, pref_id))
    if found == 0:
        return "preference not found"
    already_funded = cur.execute("SELECT * FROM user_preferences WHERE uid={} AND post_id={}".format(session.uid, post_id))
    if already_funded > 0:
        return "post already funded"
    preference = cur_dict.fetchone()
    new_amount_funded = preference.get("amount_funded") + amount
    cur.execute("UPDATE post_preferences SET amount_funded={} WHERE post_id={} AND pref_id={};".format(new_amount_funded, post_id, pref_id))
    cur.execute("INSERT INTO user_preferences (uid, post_id, pref_id, amount) VALUES({}, {}, {}, {});".format(session.uid, post_id, pref_id, amount))
    conn.commit()
    return "success"  

class handler(auth.handler):
    def callback_uri(self, provider):
        """Please return appropriate url according to your app setting.
        """
        return 'http://localhost:8080/auth/%s/callback' % provider

    def on_signin(self, provider, profile):
        """Callback when the user successfully signs in the account of the provider
        (e.g., Google account or Facebook account).
        Arguments:
          provider: google or facebook
          profile: the user profile of Google or facebook account of the user who
                   signs in.
        """
        gID = profile['gID']
        conn = pymysql.connect(host='localhost', port=3306, user='root', passwd='', db='crowdbenchmark')
        cur = conn.cursor()
        found = cur.execute("SELECT * FROM users WHERE gID=" + gID + ";")
        if found == 0:
            cur.execute("SELECT COUNT(*) FROM users;")
            uid = int(cur.fetchone()[0]) + 1
            gmail = profile['email']
            username = re.sub("@(.*$)", "", gmail)
            command = "{}, \"{}\", \"{}\", \"{}\"".format(str(uid), username, gmail, gID)
            cur.execute("INSERT INTO users (uid, username, gmail, gID) VALUES(" + command + ");")
            conn.commit()        
        session.gID = gID
        cur_dict.execute("SELECT * FROM users WHERE gID=\"" + session.gID + "\";")
        user = cur_dict.fetchone()
        session.uid = int(user.get("uid"))
        session.username = user.get("username")
        session.profile = json.dumps(profile)

        raise web.seeother('/')

class AuthPage(handler):
  def GET(self):
    self.auth_init("google")
    
class AuthCallbackPage(handler):
  def GET(self):
    self.auth_callback("google")
    
class LoginPage:
  def GET(self):
    # check '_id' in the cookie to see if the user already sign in
    if session.gID:
      # user already sign in, retrieve user profile
      #profile = json.loads( session.profile )
      #return """<html><head></head><body>
      #  <a href="/logout">Logout</a><br />
      #  Hello <b><i>%s</i></b>, your profile<br />
      #  %s<br />
      #</body></html>
      #""" % ( profile['gID'], json.dumps(profile) )
        raise web.seeother('/')
    elif session.uid:
        #return "user {} already logged in".format(getusername(session.uid))
        raise web.seeother('/')
    else:
      # user not sing in
      return """<html>
        <head>
        </head>
        <body>
          <container style="position: absolute; top: 50%; left: 50%; transform: translateX(-50%) translateY(-50%);">
            <a href="/auth/google"><img src="/static/images/google_signin.png"></a>
            <br/>
            <a href="/auth/default"><img src="/static/images/default_signin.png"></a>
            <br/>
            <a href="/auth/register"><img src="/static/images/default_signup.png"></a>
          </container>
        </body>
      </html>
      """

class DefaultAuth:
    def GET(self):
        return """<html>
        <head>
        </head>
        <body>
            <container style="position: absolute; top: 50%; left: 50%; transform: translateX(-50%) translateY(-50%);">
              <form method="post" action="/auth/default" style="text-align: center;">
                <label for="user">Username:</label><input type="text" name="username" id="user"/>
                <br/>
                <label for="pass">Password:</label><input type="password" name="password" id="pass"/>
                <br/>
                <input type="submit" value="Log In"/>
              </form>
            </container>
          </body>
        </html>
        """
    def POST(self):
        data = web.input()
        username, password = conn.escape_string(data.username), data.password
        founduser = cur.execute("SELECT uid FROM users WHERE username=\"" + username + "\";")
        if founduser == 1:
            uid = cur.fetchone()[0]
            try:
                cur.execute("SELECT password FROM users WHERE uid=" + str(uid) + ";")
                correcthash = cur.fetchone()[0]
                if hashlib.sha1(password).hexdigest() == correcthash:
                    session.uid = uid
                    session.username = username
                    raise web.seeother('/')
                else:
                    return "login error - incorrect password"
            except:
                return "login error - unknown"
        else:
            return "login error - user not found"   

class Register:
    def GET(self):
        return """<html>
        <head>
        </head>
        <body>
            <container style="position: absolute; top: 50%; left: 50%; transform: translateX(-50%) translateY(-50%);">
              <form method="post" action="/auth/register" style="text-align: center;">
                <label for="user">Username:</label><input type="text" name="username" id="user"/>
                <br/>
                <label for="pass">Password:</label><input type="password" name="password" id="pass"/>
                <br/>
                <input type="submit" value="Sign Up"/>
              </form>
            </container>
          </body>
        </html>
        """
    def POST(self):
        data = web.input()
        username = conn.escape_string(data.username)
        password = conn.escape_string(data.password)
        found = cur.execute("SELECT username FROM users WHERE username=\"" + username + "\";")
        if found == 0:
            hash = hashlib.sha1(password).hexdigest()
            print(hash)
            cur.execute("SELECT COUNT(*) FROM users;")
            uid = int(cur.fetchone()[0]) + 1
            command = "{}, \"{}\", NULL, NULL, \"{}\"".format(str(uid), username, hash)
            cur.execute("INSERT INTO users (uid, username, gmail, gID, password) VALUES(" + command + ");")
            conn.commit()
            session.uid = uid
            session.username = username
            raise web.seeother('/')
        else:
            return "username taken"

class Reset:
    def GET(self):
        session.gID = 0
        session.uid = 0
        session.kill()
        raise web.seeother('/')

class CheckUsername:
    def POST(self):
        data = web.input()
        found = cur.execute("SELECT username FROM users WHERE username=\"" + data.username + "\";")
        if found == 0:
            return "available"
        else:
            return "unavailable"
     
class Posts:
    def POST(self):
        return json.dumps(getallposts(), default=decimal_default)

class Home:
    def GET(self):
        if session.uid:
            return render.home(getallposts(), session)
        else:
            raise web.seeother('/login')
             
class Post:
    def GET(self, url):
        try:
            post_id = int(url)
        except:
            return "invalid url"
        post = describepost(post_id)
        if post['post']['giveaway_uid']:
            winner = getusername(post['post']['giveaway_uid'])
        else:
            winner = None
        print(winner)
        return render.post(post, session, winner)
    def POST(self, url):
        try:
            post_id = int(url)
        except:
            return "invalid url"
        return json.dumps(describepost(post_id), default=decimal_default)

class Fund:
    def POST(self, url):
        if session.uid:
            data = web.input()
            #check amount
            amount = int(data.amount)
            if not (amount > 0 and amount <= 100 and amount % 1 == 0):
                return "invalid amount"
            #if transaction successful
            return fund(int(url), int(data.preference), amount)
            #return json.dumps(fund, default=decimal_default)
        else:
            return "no login"

class Giveaway:
    def GET(self, url):
        found = cur_dict.execute("SELECT giveaway, giveaway_uid FROM posts WHERE post_id={}".format(url))
        if found == 0:
            return "post not found"
        post = cur_dict.fetchone()
        if post['giveaway'] == "no":
            return "post doesn't have a giveaway"
        if post['giveaway_uid'] == None:
            return "a winner has not yet been chosen"
        #return getusername(post['giveaway_uid'])
        return render.giveaway(describepost(url), session, getusername(post['giveaway_uid']))
        
           
class SubmitPost:
    def POST(self):
        if session.uid:
            data = web.input()
            cur.execute("SELECT COUNT(*) FROM posts;")
            post_id = int(cur.fetchone()[0]) + 1
            command = "{}, {}, \"{}\", \"{}\"".format(str(post_id), str(uid), data.title, data.description)
            cur.execute("INSERT INTO posts (post_id, uid, title, description) VALUES(" + command + ");")
            conn.commit()
        else:
            return "no login"
 
class PostsQuery:
    def POST(self):
        data = web.input()
        try:
            field = conn.escape_string(data.field)
            value = conn.escape_string(data.value)
        except:
            return "invalid url"
        return json.dumps(getposts(field, value))
        
class ClosePost:
    def GET(self):
        data = web.input()
        try:
            post_id = conn.escape_string(data.post_id)
        except:
            return "invalid url"
        return json.dumps(closepost(post_id))

if __name__ == '__main__': app.run()
