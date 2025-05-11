#!/bin/bash

# Function to backup sensitive files
backup_sensitive_files() {
    cp /app/peereval/settings.py /app/peereval/settings.py.backup
    cp /app/peereval/urls.py /app/peereval/urls.py.backup
    cp /app/.env /app/.env.backup
}

# Function to restore sensitive files
restore_sensitive_files() {
    cp /app/peereval/settings.py.backup /app/peereval/settings.py
    cp /app/peereval/urls.py.backup /app/peereval/urls.py
    cp /app/.env.backup /app/.env
}

# Initial backup of sensitive files
backup_sensitive_files

# Function to update from GitHub
update_from_github() {
    echo "Updating from GitHub..."
    cd /app
    git fetch origin
    if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
        echo "Changes detected, updating..."
        git reset --hard origin/main
        restore_sensitive_files
        python manage.py collectstatic --noinput
        python manage.py migrate
        echo "Update completed"
    else
        echo "No changes detected"
    fi
}

# Initial update
update_from_github

# Start background update process
while true; do
    sleep 3600  # Check every hour
    update_from_github
done &

# Start Gunicorn
exec gunicorn peereval.wsgi:application --bind 0.0.0.0:5000 --workers 3 --timeout 120
