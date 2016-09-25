#!/usr/bin/env python
# -*- coding:utf-8 -*-


import web
import urllib
import urlparse
import json
import pymysql
import re

parameters = {
  'google': {
    'app_id': None,
    'app_secret': None,
    'scope': 'https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email'
  }
}


class handler:
  """Authentication and authorization of users by OAuth 2.0
  """

  SUPPORTED_PROVIDERS = ['google']

  # provider: (auth_type, auth_url, access_token_url, parser_type)
  PROVIDERS = {
    'google':   ('oauth2',
      'https://accounts.google.com/o/oauth2/auth',
      'https://accounts.google.com/o/oauth2/token',
      '_json_parser'),
    'facebook': ('oauth2',
      'https://www.facebook.com/dialog/oauth',
      'https://graph.facebook.com/oauth/access_token',
      '_query_string_parser'),
  }

  def auth_init(self, provider):
    """Start the auth process
    """
    self._oauth2_init(provider)

  def auth_callback(self, provider):
    """Callback handler for auth process
    """
    self._oauth2_callback(provider)

  def on_signin(self, provider, profile):
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
    cur.execute("SELECT uid FROM users WHERE gID=\"" + session.gID + "\";")
    session.uID = int(cur.fetchone()[0])
    session.profile = json.dumps(profile)

  def _http_get(self, url, args=None):
    """Python HTTP GET request
    url: fullpath, e.g., https://example.org/home
    args (optional): dict used to build query string, e.g.,
      {a: '1', b: '2'} => a=1&b=2
    """
    if args == None:
      response = urllib.urlopen(url)
    else:
      query_string = urllib.urlencode(args)
      response = urllib.urlopen('%s?%s' % (url, query_string))
    return response

  def _http_post(self, url, args):
    """Python HTTP POST request
    url: fullpath, e.g., https://example.org/home
    args (optional): dict used to build POST data, e.g.,
      {a: '1', b: '2'} => a=1&b=2
    """
    data = urllib.urlencode(args)
    response = urllib.urlopen(url, data)
    return response

  def _check_provider(self, provider):
    """Check if valid provider, app_id, and app_secret
    """

    # check if the provider is supported
    if provider not in self.SUPPORTED_PROVIDERS:
      raise Exception('unsupported provider: %s' % provider)

    # check if app_id is None
    if not parameters[provider]['app_id']:
      raise Exception('invalid %s app id: %s' %
                      (provider, parameters[provider]['app_id']))

    # check if app_secret is None
    if not parameters[provider]['app_secret']:
      raise Exception('invalid %s app secret: %s' %
                      (provider, parameters[provider]['app_secret']))


  def _oauth2_init(self, provider):
    """Step 1 of oauth 2.0: init the oauth 2.0 login flow for web
    Send users to login page of provider (like Google or Facebook) for
    authentication and ask authorization of user data.
    """
    self._check_provider(provider)

    args = {
      'response_type': 'code',
      'client_id': parameters[provider]['app_id'], 
      'redirect_uri': self.callback_uri(provider),
      'scope': parameters[provider]['scope']
    }

    auth_url = self.PROVIDERS[provider][1] + '?' + urllib.urlencode(args)

    # redirect users to login page of the provider
    raise web.seeother(auth_url)

  def _oauth2_callback(self, provider):
    """Step 2 of oauth 2.0: Handling response from login page of providers.
    Case 1) If auth (authentication and authorization) not ok, raise Exception.
    Case 2) If auth ok, get access_token first, and then use the access_token to
            retrieve user profile.
    """
    self._check_provider(provider)

    # check whether auth is ok, if not ok, raise Exception.
    error = web.input().get('error')
    if error:
      raise Exception(error)

    # auth ok, get access_token
    code = web.input().get('code')

    args = {
      'code': code,
      'client_id': parameters[provider]['app_id'], 
      'client_secret': parameters[provider]['app_secret'], 
      'redirect_uri': self.callback_uri(provider),
      'grant_type': 'authorization_code'
    }

    _parser = getattr(self, '%s' % self.PROVIDERS[provider][3])
    response = _parser(
        self._http_post(self.PROVIDERS[provider][2], args).read() )
    if response.get('error'):
      raise Exception(response)

    # access_token is ready, get user profile.
    _fetcher = getattr(self, '_get_%s_user_data' % provider)
    profile = _fetcher(response['access_token'])

    # user profile ok. call on_signin function
    self.on_signin(provider, profile)

  def callback_uri(self, provider):
    """Should overwrite this method in child class.
    Implementation example: 
      return 'http://localhost:8080/auth/%s/callback' % provider
    OR
      return 'https://' + web.ctx.host + '/auth/%s/callback' % provider
    """
    raise NotImplementedError

  def _get_facebook_user_data(self, access_token):
    """Facebook APIs › Graph API
      https://graph.facebook.com/me
    returns the active user's profile
    """
    return json.loads(
        self._http_get('https://graph.facebook.com/me',
                       dict(access_token=access_token)).read()
      )

  def _get_google_user_data(self, access_token):
    """Obtaining User Profile Information from Google API
    userinfo endpoint:
      https://www.googleapis.com/oauth2/v3/userinfo
    """
    profile = json.loads(
        self._http_get('https://www.googleapis.com/oauth2/v3/userinfo',
                       dict(access_token=access_token)).read()
      )

    if 'gID' not in profile and 'sub' in profile:
      profile['gID'] = profile['sub']
    return profile

  def _query_string_parser(self, string):
    """Parse query-string-format string, and return Python dict object
    """
    return dict(urlparse.parse_qsl(string))

  def _json_parser(self, string):
    """Parse JSON format string, and return Python dict object
    """
    return json.loads(string)