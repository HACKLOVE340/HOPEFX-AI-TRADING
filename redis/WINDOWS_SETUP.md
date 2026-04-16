# Redis on Windows — Setup Guide

Redis does not have an official native Windows build. Use one of these methods:

## Option 1: WSL2 (Recommended)

```powershell
# Install WSL2 with Ubuntu
wsl --install

# Inside WSL2 terminal:
sudo apt update && sudo apt install -y redis-server
sudo service redis-server start
redis-cli ping   # should return PONG
```

Set in `.env`:
```
REDIS_URL=redis://localhost:6379/0
```

## Option 2: Docker Desktop

```powershell
docker run -d --name hopefx-redis -p 6379:6379 redis:7-alpine
```

Set in `.env`:
```
REDIS_URL=redis://localhost:6379/0
```

## Option 3: Memurai (Windows-native Redis fork)

Download from https://www.memurai.com/ — free for development.

After installation, Redis runs as a Windows service on port 6379.

## Python asyncio fix (applied automatically)

`app.py` and `run.py` automatically set `WindowsSelectorEventLoopPolicy`
on Windows so redis-py's asyncio client works correctly. No manual action
is required.

## Verifying the connection

```python
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
print(r.ping())  # True
```
