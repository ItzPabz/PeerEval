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

# Check if script was downloaded correctly
if [ ! -f "$0" ] || ! head -n 1 "$0" | grep -q "^#!/bin/bash"; then
    print_error "Script download failed or is corrupted. Please try downloading again."
    print_error "Use: curl -O https://raw.githubusercontent.com/ItzPabz/PeerEval/main/install.sh"
    exit 1
fi

# Make script executable
chmod +x "$0"

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    print_status "Installing Docker..."
    if [ -f /etc/almalinux-release ]; then
        # AlmaLinux
        sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo dnf install -y docker-ce docker-ce-cli containerd.io
        sudo systemctl enable docker
        sudo systemctl start docker
    else
        print_error "Docker installation is only automated for AlmaLinux. Please install Docker manually."
        exit 1
    fi
fi

if ! command -v git &> /dev/null; then
    print_status "Installing Git..."
    if [ -f /etc/almalinux-release ]; then
        sudo dnf install -y git
    else
        print_error "Git is not installed. Please install Git first."
        exit 1
    fi
fi

# Check for NPM and install if not present
if ! command -v npm &> /dev/null; then
    print_status "Installing NPM..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Check for AlmaLinux
        if [ -f /etc/almalinux-release ]; then
            # AlmaLinux
            curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
            sudo dnf install -y nodejs
        else
            # Other Linux (Ubuntu/Debian)
            curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
            sudo apt-get install -y nodejs
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        brew install node
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        # Windows
        print_error "Please install Node.js manually from https://nodejs.org/"
        exit 1
    else
        print_error "Unsupported operating system. Please install Node.js manually."
        exit 1
    fi
fi

# Get NPM path
NPM_PATH=$(which npm)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    NPM_PATH="$NPM_PATH.cmd"
fi

read -p "Enter institution name (e.g., Monsters University): " INST_NAME
read -p "Enter institution short name (e.g., MU): " INST_SHORT_NAME
read -p "Enter site URL (e.g., peereval.example.com): " SITE_URL

if [ -d "PeerEval" ]; then
    print_status "Updating existing repository..."
    cd PeerEval
    # Stash any local changes
    git stash
    git pull
    # Apply stashed changes back
    git stash pop
else
    print_status "Cloning repository..."
    git clone https://github.com/ItzPabz/PeerEval.git
    cd PeerEval
fi

print_status "Updating institution settings..."
sed -i "s|INST_NAME = '.*'|INST_NAME = '$INST_NAME'|" peereval/settings.py
sed -i "s|INST_SHORT_NAME = '.*'|INST_SHORT_NAME = '$INST_SHORT_NAME'|" peereval/settings.py
sed -i "s|ALLOWED_HOSTS = \[.*\]|ALLOWED_HOSTS = \['$SITE_URL'\]|" peereval/settings.py
sed -i "s|NPM_BIN_PATH = '.*'|NPM_BIN_PATH = '$NPM_PATH'|" peereval/settings.py

print_status "Building Docker image..."
docker build -t peereval .

print_status "Creating Docker network..."
docker network create peereval-network || true

print_status "Starting PostgreSQL container..."
docker run --name peereval-db \
    -e POSTGRES_DB=peereval \
    -e POSTGRES_USER=peereval \
    -e POSTGRES_PASSWORD=peereval \
    --network peereval-network \
    -d postgres:13

print_status "Waiting for database to be ready..."
sleep 10

print_status "Running database migrations..."
docker run --rm \
    --network peereval-network \
    -e DATABASE_URL=postgres://peereval:peereval@peereval-db:5432/peereval \
    peereval python manage.py migrate

print_status "Collecting static files..."
docker run --rm \
    --network peereval-network \
    -e DATABASE_URL=postgres://peereval:peereval@peereval-db:5432/peereval \
    peereval python manage.py collectstatic --noinput

print_status "Starting application container..."
docker run -d \
    --name peereval-app \
    --network peereval-network \
    -e DATABASE_URL=postgres://peereval:peereval@peereval-db:5432/peereval \
    -p 8000:8000 \
    peereval

print_status "Installation completed successfully!"
print_status "The application should now be running at https://$SITE_URL"
print_status "Database has been migrated from SQLite to PostgreSQL"
print_status "To create an admin user, please use: python manage.py createadmin"
print_status "Please ensure your web server (e.g., Nginx) is configured to proxy requests to port 8000"