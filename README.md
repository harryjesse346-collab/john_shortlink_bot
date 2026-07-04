# 🔗 John's Shortlink Bot

A powerful Telegram bot for URL shortening with click tracking and user statistics, built with Flask and MongoDB, optimized for Railway deployment.

## ✨ Features

- 🔗 Instant URL shortening
- 🎨 Custom short codes support
- 📊 Click tracking and analytics
- 📝 User link management
- 👤 User statistics
- 🎯 Simple inline keyboard interface
- 📱 Mobile-friendly redirect page
- 🗄️ MongoDB or in-memory storage

## 🚀 Deployment on Railway

### Quick Deploy (Recommended)

1. Click the "Deploy on Railway" button or go to [Railway.app](https://railway.app)
2. Create a new project
3. Select "Deploy from GitHub repo"
4. Connect your GitHub account
5. Select this repository
6. Add environment variables (see below)
7. Wait for deployment to complete

### Manual Deployment

1. Fork this repository to your GitHub
2. Go to Railway.app and click "New Project"
3. Choose "Deploy from GitHub repo"
4. Select your forked repository
5. Add the following environment variables:
   - `TELEGRAM_BOT_TOKEN` - Your bot token from @BotFather
6. Railway will automatically deploy your bot

## 🔧 Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | ✅ Yes | Your bot token from @BotFather | `123456:ABC-DEF123` |
| `MONGODB_URI` | ❌ No | MongoDB connection string | `mongodb://user:pass@host` |
| `DATABASE_NAME` | ❌ No | Database name | `shortlink_bot` |
| `BASE_URL` | ❌ No | Your app's public URL | `https://your-app.up.railway.app` |
| `PORT` | ❌ No | Port number | `5000` |

## 📱 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and show welcome message |
| `/help` | Show help and usage guide |
| `/stats` | View your statistics |
| `/mylinks` | View all your shortened URLs |
| `/custom {url} {code}` | Create custom short URL |

### Examples
