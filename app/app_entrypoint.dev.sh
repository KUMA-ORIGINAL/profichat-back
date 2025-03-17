#!/bin/sh

# Run database migrations
python manage.py migrate

# Uncomment this line if you need to collect static files
# python manage.py collectstatic --noinput

# Start the Django development server on all interfaces, port 8000
python manage.py runserver 0.0.0.0:8000
