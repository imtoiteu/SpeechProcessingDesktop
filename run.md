# stop the current server

lsof -ti :8000 | xargs kill

pkill -f whisperlivekit-server

# relaunch with auto-detect (badge will reflect the REAL spoken language; handles English)

whisperlivekit-server \
 --model large-v3-turbo \
 --backend mlx-whisper \
 --backend-policy simulstreaming \
 --language auto \
 --host localhost --port 8000
