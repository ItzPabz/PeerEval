#!/bin/bash

# Stop only the web container
docker stop peereval-web
docker rm peereval-web

# Rebuild and start only the web container
docker-compose up -d --build peereval-web

# Show logs for the web container
docker-compose logs -f peereval-web 