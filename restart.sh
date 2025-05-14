#!/bin/bash

# Stop all containers
docker-compose down

# Remove all containers and volumes
docker-compose rm -f
docker volume prune -f

# Rebuild and start containers
docker-compose up -d --build

# Show logs
docker-compose logs -f 