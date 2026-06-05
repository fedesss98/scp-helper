release: python manage.py migrate --noinput
web: gunicorn vogapp.wsgi --log-file -
worker: python bot/run_bot.py
