#!/bin/sh

echo "Checking for migrations..."
python manage.py makemigrations

echo "Running migrations..."
python manage.py migrate

echo "Starting server..."
python manage.py runserver 0.0.0.0:8000
