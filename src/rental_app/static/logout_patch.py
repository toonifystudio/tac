from flask import session, redirect, url_for
from rental_app.web import app


@app.route('/logout')
def logout_route():
    session.pop('user', None)
    return redirect(url_for('login'))
