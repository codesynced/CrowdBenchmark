import web
import json, decimal
import pymysql
import auth
import re
import hashlib
from numpy.random import choice
#chat
import os
import threading
import time
import datetime
import random

# create Google app & get app ID/secret from:
# https://cloud.google.com/console
auth.parameters['google']['app_id'] = '744074363989-uvvip7u9a5s8p45chbub04eodgb97pns.apps.googleusercontent.com'
auth.parameters['google']['app_secret'] = 'oWgYfKuVSEZ3yPEkkyPnBEsV'

# messages is the list of message lines. thread_lock is a dict that
# assigns locks to waiting threads. session_pos is a dict that assigns
# their current position in the message list to sessions.
thread_lock = {}


render = web.template.render('templates/')

urls = (
    r"/login", "LoginPage",
    r"/auth/google", "AuthPage",
    r"/auth/google/callback", "AuthCallbackPage",
#    '/auth/default', 'DefaultAuth',
    '/auth/register', 'Register',
    '/logout', 'Reset',
    '/availability', 'CheckUsername',
    '/post/([0-9]*)', 'Post',
    '/post/([0-9]*)/fund', 'Fund',
    '/post/([0-9]*)/cancel', 'Cancel',
    '/submit', 'SubmitPost',
    '/posts/search', 'PostsQuery',
    '/script/post/close', 'ClosePost',
    '/posts', 'Posts',
    '/', 'Redirect',
    '/home', 'Home',
    '/user/(.*)', 'User',
    '/chat/([0-9]+)', 'Frame',
    '/chat/([0-9]+)/longpoll/([0-9]+)', 'LongPoll',
    '/chat/([0-9]+)/readall', 'ReadAll',
    '/chat/([0-9]+)/send', 'Say',
    '/chat/stop', 'Stop',
    '/chat/create', 'CreateChat'
)

web.config.debug = False

app = web.application(urls, globals())

store = web.session.DiskStore('sessions')
session = web.session.Session(app, store,
                              initializer={'uid': None, 'username': 'Guest', 'gID': None, 'profile': None, 'posts_viewed': []})

conn = pymysql.connect(host='localhost', port=3306, user='root', passwd='', db='crowdbenchmark')
conn_dict = pymysql.connect(host='localhost', port=3306, user='root', passwd='', db='crowdbenchmark', cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()
cur_dict = conn_dict.cursor()

def decimal_default(obj):
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    elif isinstance(obj, datetime.datetime):
        return str(obj)
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
        #timeposted = post['timeposted']
        #post['timeposted'] = str(timeposted)
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

def getpostsby(query, amount, page):
    offset = amount * page
    cur_dict.execute("SELECT * FROM posts ORDER BY {} DESC LIMIT {} OFFSET {};".format(query, amount, offset))
    posts = cur_dict.fetchall()
    for post in posts:
        post_id = post.get("post_id")
        cur_dict.execute("SELECT * FROM post_preferences WHERE post_id={};".format(post_id))
        post_preferences = cur_dict.fetchall()
        post['preferences'] = post_preferences
        cur.execute("SELECT username FROM users WHERE uid={};".format(post.get("uid")))
        post['username'] = cur.fetchone()[0]
    return posts

def describepost(post_id):
    found = cur_dict.execute("SELECT * FROM posts WHERE post_id={};".format(post_id))
    if found == 0:
        return "post not found"
    post = cur_dict.fetchall()[0]
    cur_dict.execute("SELECT * FROM post_preferences WHERE post_id={};".format(post_id))
    post['preferences'] = cur_dict.fetchall()
    cur.execute("SELECT username FROM users WHERE uid={};".format(post.get("uid")))
    post['username'] = cur.fetchone()[0]
    return post

def describepostsby(query, value):
    if type(value) is str:
        command = "SELECT * FROM posts WHERE {}=\"{}\";".format(query, value)
    else:
        command = "SELECT * FROM posts WHERE {}={};".format(query, value)
    cur_dict.execute(command)
    posts = cur_dict.fetchall()
    for post in posts:
        cur_dict.execute("SELECT * FROM post_preferences WHERE post_id={};".format(post['post_id']))
        post['preferences'] = cur_dict.fetchall()
        cur.execute("SELECT username FROM users WHERE uid={};".format(post['uid']))
        post['username'] = cur.fetchone()[0]
    return posts

def giveaway(paying_users):
    sum = 0
    for user in paying_users:
        sum = sum + user['amount']
    uid = choice([user['uid'] for user in paying_users], p=[user['amount'] / float(sum) for user in paying_users])
    return uid

def closepost(post_id):
    conn_dict.commit()
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
    cur_dict.execute("""SELECT * FROM post_preferences WHERE post_id={} AND amount_funded >= pref_cost;""".format(post_id))
    preferences = cur_dict.fetchall()
    #--check if any preferences were eligible--#
    if len(prefences) == 0:
        return "post failed: not enough funds"
    #------------------------------------------#
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
    conn_dict.commit()
    #return
    return {"winning preference": winning_preference, "paying users": paying_users, "nonpaying users": nonpaying_users, "winning user": giveaway_uid}  

def getusername(uid):
    found = cur.execute("SELECT username FROM users WHERE uid=\"" + str(uid) + "\";")
    if found == 0:
        return "user not found"
    else:
        return cur.fetchone()[0]
        
def fund(post_id, pref_id, amount):
    conn_dict.commit()
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
    conn_dict.commit()
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
            conn_dict.commit()     
        session.gID = gID
        cur_dict.execute("SELECT * FROM users WHERE gID=\"" + session.gID + "\";")
        user = cur_dict.fetchone()
        session.uid = int(user.get("uid"))
        session.username = user.get("username")
        session.profile = json.dumps(profile)

        raise web.seeother('/home')

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
        raise web.seeother('/home')
    elif session.uid:
        #return "user {} already logged in".format(getusername(session.uid))
        raise web.seeother('/home')
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

#class DefaultAuth:
#    def GET(self):
#        return """<html>
#        <head>
#        </head>
#        <body>
#            <container style="position: absolute; top: 50%; left: 50%; transform: translateX(-50%) translateY(-50%);">
#              <form method="post" action="/auth/default" style="text-align: center;">
#                <label for="user">Username:</label><input type="text" name="username" id="user"/>
#                <br/>
#                <label for="pass">Password:</label><input type="password" name="password" id="pass"/>
#                <br/>
#                <input type="submit" value="Log In"/>
#              </form>
#            </container>
#          </body>
#        </html>
#        """
#    def POST(self):
#        data = web.input()
#        username, password = conn.escape_string(data.username), data.password
#        founduser = cur.execute("SELECT uid FROM users WHERE username=\"" + username + "\";")
#        if founduser == 1:
#            uid = cur.fetchone()[0]
#            try:
#                cur.execute("SELECT password FROM users WHERE uid=" + str(uid) + ";")
#                correcthash = cur.fetchone()[0]
#                if hashlib.sha1(password).hexdigest() == correcthash:
#                    session.uid = uid
#                    session.username = username
#                    raise web.seeother('/home')
#                else:
#                    return "login error - incorrect password"
#            except:
#                return "login error - unknown"
#        else:
#            return "login error - user not found"   

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
            cur.execute("SELECT COUNT(*) FROM users;")
            uid = int(cur.fetchone()[0]) + 1
            command = "{}, \"{}\", NULL, NULL, \"{}\"".format(str(uid), username, hash)
            cur.execute("INSERT INTO users (uid, username, gmail, gID, password) VALUES(" + command + ");")
            conn.commit()
            conn_dict.commit()
            session.uid = uid
            session.username = username
            raise web.seeother('/home')
        else:
            return "username taken"

class Reset:
    def GET(self):
        session.gID = 0
        session.uid = 0
        session.kill()
        raise web.seeother('/home')

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

class Redirect:
    def GET(self):
        if session.uid:
            return web.seeother('/home')
        else:
            return web.seeother('/login')

class Home:
    def GET(self):
        if session.uid:
            try:
                page = int(web.input().page)
            except:
                page = 0
            try:
                amount = int(web.input().amount)
            except:
                amount = 10
            offset = page * amount
            cur.execute("SELECT post_id FROM user_preferences WHERE uid={};".format(session.uid))
            posts_funding = []
            for post in cur.fetchall():
                full_post = describepost(post[0])
                if full_post is not "post not found":
                    posts_funding.append(full_post)
            cur.execute("SELECT post_id FROM posts WHERE uid={};".format(session.uid))
            my_posts = []
            for post in cur.fetchall():
                my_posts.append(describepost(post[0]))
            return render.home(getpostsby('hits', amount, page), posts_funding, my_posts, session, page)
        else:
            raise web.seeother('/login')

class Post:
    def GET(self, url):
        try:
            post_id = int(url)
        except:
            return "invalid url"
        if post_id not in session.posts_viewed:
            session.posts_viewed.append(post_id)
            cur.execute("UPDATE posts SET hits = hits + 1 WHERE post_id={};".format(post_id))
            conn.commit()
        post = describepost(post_id)
        if post['giveaway_uid']:
            winner = getusername(post['giveaway_uid'])
        else:
            winner = None
        found = cur.execute("SELECT uid FROM user_preferences WHERE post_id={} AND uid={};".format(post_id, session.uid))
        is_funding = found > 0
        return render.post(post, session, winner, is_funding)
    def POST(self, url):
        try:
            post_id = int(url)
        except:
            return "invalid url"
        return json.dumps(describepost(post_id), default=decimal_default)

class User:
    def GET(self, url):
        cur.execute("SELECT uid FROM users WHERE username=\"{}\";".format(url))
        try:
            uid = cur.fetchone()[0]
            print(uid)
        except:
            return "user not found"
        cur.execute("SELECT post_id FROM posts WHERE uid={};".format(uid))
        posts = []
        for post in cur.fetchall():
            posts.append(describepost(post[0]))
        return render.user(url, posts, session)

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
        
class Cancel:
    def GET(self, url):
        post_id = int(url)
        found = cur_dict.execute("SELECT * FROM posts WHERE post_id={}".format(post_id))
        if found == 0:
            return "post not found"
        post = cur_dict.fetchone()
        if session.uid != post['uid']:
            return "you do not have permission to cancel this post"
        if post['status'] == "closed":
            return "a closed post cannot be cancelled"
        paying_users = []
        cur_dict.execute("SELECT * FROM user_preferences WHERE post_id={}".format(post_id))
        for user in cur_dict.fetchall():
            paying_users.append(user['uid'])
        #give the users back their money!
        #--------Not Implemented-------#
        #Delete Stuff
        cur.execute("DELETE FROM posts WHERE post_id={}".format(post_id))
        cur.execute("DELETE FROM post_preferences WHERE post_id={}".format(post_id))
        cur.execute("DELETE FROM user_preferences WHERE post_id={}".format(post_id))
        conn.commit()
        conn_dict.commit()
        raise web.seeother('/home')
             
           
class SubmitPost:
    def GET(self):
        return render.submit(session)
    def POST(self):
        if session.uid:
            data = web.input()
            cur.execute("SELECT COUNT(*) FROM posts;")
            post_id = int(cur.fetchone()[0]) + 1
            try:
                if data.giveaway == "on":
                    giveaway = "yes"
            except:
                giveaway = "no"
            command = "{}, {}, \"{}\", \"{}\", \"open\", \"{}\", 0".format(post_id, session.uid, data.title, data.description, giveaway)
            cur.execute("INSERT INTO posts (post_id, uid, title, description, status, giveaway, hits) VALUES(" + command + ");")
            items = []
            for i in range(0, 4):
                try:
                   exec("items.append({data.item_%d_desc: data.item_%d_cost})" % (i, i))
                except:
                    pass
            item_counter = 0
            for item in items:
                cur.execute("INSERT INTO post_preferences (post_id, pref_id, pref_desc, pref_cost, amount_funded) VALUES({}, {}, \"{}\", {}, 0)".format(post_id, item_counter, item.keys()[0], item.values()[0]))
                item_counter += 1
            conn.commit()
            conn_dict.commit()
            raise web.seeother('/post/' + str(post_id))
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
        
chats = []
        
class CreateChat:
    def GET(self):
        data = web.input()
        existing_chat = [chat for chat in chats if session.uid in chat['users'] and int(data.recipient) in chat['users']]
        if len(existing_chat) == 0:
            id = random.randint(0, 2000000000)
            chats.append({'id': id, 'users': [session.uid, int(data.recipient)], 'messages': [], 'session_pos': {}})
        else:
            id = existing_chat[0]['id']
        raise web.seeother("/chat/" + str(id))

class LongPoll:
    def GET(self, url, session_id):
        web.header('Content-type', 'text/html')
        thread_id = str(threading.current_thread())
        id = int(url)
        try:
            chat = [chat for chat in chats if chat['id'] == id][0]
        except:
            yield "Chat Not Found"
        if session.uid not in chat['users']:
            yield "You Do Not Have Permission to View This Chat"
        if session.uid not in chat['session_pos']:
            chat['session_pos'][session.uid] = 0
        if chat['session_pos'][session.uid] == len(chat['messages']):
            thread_lock[thread_id] = threading.Event()
            thread_lock[thread_id].clear()
            thread_lock[thread_id].wait()
        while chat['session_pos'][session.uid] < len(chat['messages']):
            msg = chat['messages'][chat['session_pos'][session.uid]]
            yield '<div>%s</div>\n' % msg
            chat['session_pos'][session.uid] += 1

class ReadAll:
    def GET(self, url):
        web.header('Content-type', 'text/html')
        thread_id = str(threading.current_thread())
        id = int(url)
        try:
            chat = [chat for chat in chats if chat['id'] == id][0]
        except:
            yield "Chat Not Found"
        pos = 0
        while True:
            if pos == len(chat['messages']):
                thread_lock[thread_id] = threading.Event()
                thread_lock[thread_id].clear()
                thread_lock[thread_id].wait()
            yield chat['messages'][pos] + '\n'
            pos += 1

class Say:
    def POST(self, url):
        id = int(url)
        try:
            chat = [chat for chat in chats if chat['id'] == id][0]
        except:
            return "Chat Not Found"
        if session.uid not in chat['users']:
            return "You Do Not Have Permission to Write Messages in This Chat"
        line = web.input()['l']
        chat['messages'].append(session.username + ": " + line)
        for thread in thread_lock:
            thread_lock[thread].set()
        return "Line '%s' accepted." % line

class Stop:
    def GET(self):
        #os._exit(0)
        return

class Frame:
    def GET(self, url):
        id = int(url)
        try:
            chat = [chat for chat in chats if chat['id'] == id][0]
        except:
            return "Chat Not Found"
        input = web.input()
        if 'l' in input:
            line = input['l']
            chat['messages'].append(line)
            for thread in thread_lock:
                thread_lock[thread].set()
        randnum = random.randint(0, 2000000000)
        page = """
        <html>
            <head>
                <title>Minimal web chat</title>
                <script type="text/javascript" src="/static/jquery.js"></script>
            </head>
            <body>
                <div id="chat" style="height: 400px; overflow-x: hidden; overflow: auto;"></div>
                <input id="text">
                </input>
                <input type="button" value="Send" onclick="sendMsg()">
                <input type="button" value="Stop" onclick="stop()">
                </input>
                <script type="text/javascript">
                    $('#text').keypress(function(event) {
                        if (event.keyCode == '13')
                            sendMsg();
                    });
                    function sendMsg() {
                        var text = $('#text');
                        var msg = text.val();
                        $.post('/chat/%d/send', {'l': msg});
                        text.val('');
                    }

                    function stop() {
                        $.ajax({url: '/stop'});
                        $('#chat').append('&nbsp;&nbsp;&nbsp;&nbsp;*** Stop. You may close the window. ***');
                    }


                    function getMsg() {
                        $.ajax({
                            url: '/chat/%d/longpoll/%d',
                            dataType: 'text',
                            type: 'get',
                            success: function(line) {
                                $('#chat').append(line);
                                setTimeout('getMsg()', 1000);
                                }
                        });
                    }
                    getMsg();
                </script>
            </body>
        </html>
        """ % (id, id, randnum)
        return page

if __name__ == '__main__': app.run()
