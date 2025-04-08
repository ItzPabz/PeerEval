#!/bin/bash

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[*] $1${NC}"
}

print_error() {
    echo -e "${RED}[!] $1${NC}"
}

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

if ! command -v git &> /dev/null; then
    print_error "Git is not installed. Please install Git first."
    exit 1
fi

read -p "Enter institution name (e.g., Monsters University): " INST_NAME
read -p "Enter institution short name (e.g., MU): " INST_SHORT_NAME
read -p "Enter institution color (e.g., blue): " INST_COLOR
read -p "Enter site URL (e.g., peereval.example.com): " SITE_URL

if [ -d "PeerEval_REDUX" ]; then
    print_status "Updating existing repository..."
    cd PeerEval_REDUX
    git pull
else
    print_status "Cloning repository..."
    git clone https://github.com/ItzPabz/PeerEval.git
    cd PeerEval_REDUX
fi

print_status "Updating institution settings..."
sed -i "s/INST_NAME = '.*'/INST_NAME = '$INST_NAME'/" peereval/settings.py
sed -i "s/INST_SHORT_NAME = '.*'/INST_SHORT_NAME = '$INST_SHORT_NAME'/" peereval/settings.py
sed -i "s/INST_COLOR = '.*'/INST_COLOR = '$INST_COLOR'/" peereval/settings.py
sed -i "s/ALLOWED_HOSTS = \[.*\]/ALLOWED_HOSTS = \['$SITE_URL'\]/" peereval/settings.py

print_status "Installing Python requirements..."
docker-compose run --rm web pip install -r requirements.txt

print_status "Building and starting Docker containers..."
docker-compose build
docker-compose up -d

print_status "Waiting for containers to be ready..."
sleep 10

print_status "Running database migrations..."
docker-compose exec web python manage.py migrate

read -p "Do you want to create an admin user? (y/n): " CREATE_ADMIN
if [ "$CREATE_ADMIN" = "y" ]; then
    docker-compose exec web python manage.py createadmin
fi

print_status "Collecting static files..."
docker-compose exec web python manage.py collectstatic --noinput

print_status "Installation completed successfully!"
print_status "The application should now be running at https://$SITE_URL"
print_status "Please ensure your web server (e.g., Nginx) is configured to proxy requests to port 8000"