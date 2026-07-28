#!/usr/bin/env python3
from rental_app.web import app

if __name__ == '__main__':
    app.run(debug=True, port=8080)
