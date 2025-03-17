#!/bin/sh

python manage.py loaddata user.json
python manage.py loaddata patient.json
