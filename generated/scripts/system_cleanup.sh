#!/bin/bash
# TIMPS System Optimizer — REVIEW BEFORE RUNNING
# This script disables startup items identified as non-essential.

# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/com.google.keystone.xpcservice.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/com.google.keystone.agent.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/homebrew.mxcl.mysql.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/homebrew.mxcl.mongodb-community.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/ai.perplexity.CometUpdater.wake.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/ai.perplexity.keystone.agent.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/homebrew.mxcl.ollama.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/ai.perplexity.keystone.xpcservice.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/homebrew.mxcl.mysql@8.0.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/homebrew.mxcl.postgresql@14.plist
# launchctl unload -w /Users/sandeepreddy/Library/LaunchAgents/com.google.GoogleUpdater.wake.plist
# osascript -e 'tell application "System Events" to delete login item "Wispr Flow"'
# osascript -e 'tell application "System Events" to delete login item "tldv"'
# osascript -e 'tell application "System Events" to delete login item "Comet"'
# osascript -e 'tell application "System Events" to delete login item "GeminiAppLauncher"'
# osascript -e 'tell application "System Events" to delete login item "Clicky"'

echo 'Remove the # comment prefix from lines you want to execute.'