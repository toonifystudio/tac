from flask import session, redirect, url_for, request, render_template_string
from functools import wraps
from rental_app.config_env import get_config

cfg = get_config()

login_page = """
<!doctype html>
<title>Login</title>
<h2>Login</h2>
<form method="post">
  <label>Username: <input type="text" name="username"></label><br/>
  <label>Password: <input type="password" name="password"></label><br/>
  <input type="submit" value="Login">
</form>
"""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user'):
            return f(*args, **kwargs)
        return redirect(url_for('login', next=request.path))
    return decorated


def login_view():
    from flask import request, session
    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')
        if user == cfg.admin_user and pw == cfg.admin_pass:
            session['user'] = user
            next_url = request.args.get('next') or '/'
            return redirect(next_url)
        else:
            return render_template_string(login_page + '<p style="color:red">Invalid</p>')
    return render_template_string(login_page)


def logout_view():
    from flask import session, redirect, url_for
    session.pop('user', None)
    return redirect(url_for('login'))
